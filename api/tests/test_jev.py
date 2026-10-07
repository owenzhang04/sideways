from types import SimpleNamespace

import pytest
from typesafe_sdk import TypeSafeAPIConnectionError

from sideways.engine.jev import Candidate, JevRanker
from sideways.engine.pipeline import Recommender, RecRequest
from tests.fakes import FakeDeezer, FakeListenBrainz, FakeMusicBrainz
from tests.test_pipeline import ARTISTS, MBIDS, RELATED, SIMILAR, TAGS


class FakeTypeSafe:
    """Answers by candidate name; names in `fail` raise like a network error."""

    def __init__(self, fits: dict[str, float], steer: dict[str, float] | None = None, fail=()):
        self.fits = fits
        self.steer = steer
        self.fail = set(fail)
        self.states: list[dict] = []

    async def system_one(self, state, questions, model):
        self.states.append(state)
        name = state["candidate"]["name"]
        if name in self.fail:
            raise TypeSafeAPIConnectionError("down")
        nouls = {"fits_taste": SimpleNamespace(noul=self.fits.get(name, 0.5))}
        if "matches_steer" in questions:
            nouls["matches_steer"] = SimpleNamespace(noul=(self.steer or {}).get(name, 0.5))
        return SimpleNamespace(nouls=nouls)


def cands(*names: str) -> list[Candidate]:
    return [Candidate(n.lower(), n, ["tag"], ["Seed"]) for n in names]


async def test_scores_each_candidate_and_only_asks_steer_when_given():
    client = FakeTypeSafe({"A": 0.9, "B": 0.2})
    ranker = JevRanker(client, "jev-test")
    plain = await ranker.score(["Seed"], ["tag"], "", cands("A", "B"))
    assert plain["a"].fits_taste == pytest.approx(0.9) and plain["a"].matches_steer is None
    assert "request" not in client.states[0]["listener"]

    steered = await ranker.score(["Seed"], [], "more upbeat", cands("A"))
    assert steered["a"].matches_steer == pytest.approx(0.5)
    assert client.states[-1]["listener"]["request"] == "more upbeat"


async def test_failed_candidates_are_left_out_not_fatal():
    ranker = JevRanker(FakeTypeSafe({"A": 0.9}, fail={"B"}), "jev-test")
    result = await ranker.score(["Seed"], [], "", cands("A", "B"))
    assert set(result) == {"a"}


async def test_pipeline_lets_jev_reorder_and_warns_when_jev_is_down():
    deezer = FakeDeezer(ARTISTS, RELATED)
    lb, mb = FakeListenBrainz(SIMILAR, TAGS), FakeMusicBrainz(MBIDS)
    plain = await Recommender(deezer, lb, mb).recommend(RecRequest(seeds=[1, 2]))
    assert plain.recs[0].name == "Shared Neighbor"

    # Taste fit alone only nudges; it can't overturn a clear graph lead.
    prefers_lb = {"LB Only": 0.99, "Shared Neighbor": 0.01}
    nudged = await Recommender(deezer, lb, mb, JevRanker(FakeTypeSafe(prefers_lb), "j")).recommend(
        RecRequest(seeds=[1, 2])
    )
    assert nudged.jev_used and nudged.recs[0].name == "Shared Neighbor"

    # An explicit request the top pick fails is allowed to reorder the list.
    jev = JevRanker(FakeTypeSafe(prefers_lb, steer=prefers_lb), "j")
    steered = await Recommender(deezer, lb, mb, jev).recommend(
        RecRequest(seeds=[1, 2], steer="instrumental only")
    )
    names = [r.name for r in steered.recs]
    assert names.index("LB Only") < names.index("Shared Neighbor")

    every = {a.name for a in ARTISTS} | {"Not On Deezer"}
    down = JevRanker(FakeTypeSafe({}, fail=every), "jev-test")
    result = await Recommender(deezer, lb, mb, down).recommend(RecRequest(seeds=[1, 2]))
    assert not result.jev_used
    assert any("Jev" in w for w in result.warnings)
    assert [r.name for r in result.recs] == [r.name for r in plain.recs]
