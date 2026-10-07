import os

import pytest

from sideways.engine.pipeline import Recommender, RecRequest
from sideways.engine.steer import GLiClassScorer, SteerCandidate, describe, split_request
from tests.fakes import FakeDeezer, FakeListenBrainz, FakeMusicBrainz
from tests.test_pipeline import ARTISTS, MBIDS, RELATED, SIMILAR, TAGS


class FakeSteer:
    def __init__(self, matches: dict[str, float], status: str = "ready", fail: bool = False):
        self.matches = matches
        self._status = status
        self.fail = fail
        self.requests: list[tuple[str, list[SteerCandidate]]] = []

    @property
    def status(self) -> str:
        return self._status

    async def score(self, request: str, candidates: list[SteerCandidate]) -> dict[str, float]:
        if self.fail:
            raise RuntimeError("model crashed")
        self.requests.append((request, candidates))
        return {c.key: self.matches.get(c.name, 0.5) for c in candidates}


def make(steer: FakeSteer | None) -> Recommender:
    return Recommender(
        FakeDeezer(ARTISTS, RELATED), FakeListenBrainz(SIMILAR, TAGS), FakeMusicBrainz(MBIDS), steer
    )


def test_split_request():
    assert split_request("More upbeat, 90s and Female vocals") == [
        "more upbeat",
        "90s",
        "female vocals",
    ]
    assert split_request("  ") == []
    assert split_request("a, a; b / c, d, e") == ["a", "b", "c", "d"]
    assert split_request("rock and roll")[0] == "rock"


def test_describe_uses_tags_or_says_unknown():
    assert describe(SteerCandidate("k", "Slowdive", ["shoegaze"])) == "Slowdive. Genres: shoegaze."
    assert describe(SteerCandidate("k", "X", [])) == "X. Genres: unknown."


async def test_request_reorders_list_and_reports_match():
    plain = await make(None).recommend(RecRequest(seeds=[1, 2]))
    assert plain.recs[0].name == "Shared Neighbor" and not plain.steered

    steer = FakeSteer({"LB Only": 0.99, "Shared Neighbor": 0.01})
    result = await make(steer).recommend(RecRequest(seeds=[1, 2], steer="jazz"))
    names = [r.name for r in result.recs]
    assert result.steered
    assert names.index("LB Only") < names.index("Shared Neighbor")
    assert result.recs[names.index("LB Only")].steer_match == pytest.approx(0.99)
    request, candidates = steer.requests[0]
    assert request == "jazz"
    lb_only = next(c for c in candidates if c.name == "LB Only")
    assert lb_only.tags == ["jazz"]


async def test_no_request_means_model_is_not_called():
    steer = FakeSteer({})
    result = await make(steer).recommend(RecRequest(seeds=[1, 2], steer="   "))
    assert steer.requests == [] and not result.steered and result.warnings == []


@pytest.mark.parametrize(
    ("steer", "warning"),
    [
        (FakeSteer({}, status="loading"), "warming up"),
        (FakeSteer({}, status="failed"), "unavailable"),
        (FakeSteer({}, fail=True), "failed"),
    ],
)
async def test_unusable_model_falls_back_to_graph_order_with_warning(steer, warning):
    plain = await make(None).recommend(RecRequest(seeds=[1, 2]))
    result = await make(steer).recommend(RecRequest(seeds=[1, 2], steer="jazz"))
    assert not result.steered
    assert any(warning in w for w in result.warnings)
    assert [r.name for r in result.recs] == [r.name for r in plain.recs]


async def test_scorer_returns_nothing_until_loaded():
    scorer = GLiClassScorer("not/loaded")
    assert scorer.status == "loading"
    assert await scorer.score("jazz", [SteerCandidate("k", "X", [])]) == {}


@pytest.mark.skipif(
    not os.environ.get("TEST_STEER_MODEL"),
    reason="set TEST_STEER_MODEL=knowledgator/gliclass-base-v3.0 to run the real model",
)
async def test_real_model_ranks_obvious_matches_first():
    import asyncio

    scorer = GLiClassScorer(os.environ["TEST_STEER_MODEL"])
    scorer.start_loading()
    while scorer.status == "loading":
        await asyncio.sleep(0.5)
    assert scorer.status == "ready"
    cands = [
        SteerCandidate("daft", "Daft Punk", ["electronic", "french house", "dance"]),
        SteerCandidate("evans", "Bill Evans", ["jazz", "cool jazz", "piano"]),
        SteerCandidate("mbv", "my bloody valentine", ["shoegaze", "noise pop", "dream pop"]),
    ]
    for request, expected in [
        ("upbeat dance music", "daft"),
        ("calm instrumental", "evans"),
        ("loud guitars", "mbv"),
    ]:
        scores = await scorer.score(request, cands)
        assert max(scores, key=scores.__getitem__) == expected, (request, scores)
