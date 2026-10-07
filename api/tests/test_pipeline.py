import pytest

from sideways.engine.pipeline import NoSeedsError, Recommender, RecRequest
from tests.fakes import FakeDeezer, FakeListenBrainz, FakeMusicBrainz, artist

ARTISTS = [
    artist(1, "Seed One", 50_000),
    artist(2, "Seed Two", 40_000),
    artist(10, "Shared Neighbor", 30_000),
    artist(11, "Only Deezer", 20_000),
    artist(12, "Famous", 9_000_000),
    artist(13, "Disliked", 10_000),
    artist(14, "Disliked Friend", 10_000),
    artist(20, "LB Only", 3_000),
]
RELATED = {1: [10, 11, 12], 2: [10, 12], 13: [14]}
SIMILAR = {
    "m1": [("m10", "Shared Neighbor", 100), ("m20", "LB Only", 80), ("mx", "Not On Deezer", 70)],
    "m2": [("m10", "Shared Neighbor", 50)],
}
MBIDS = {"Seed One": "m1", "Seed Two": "m2"}
TAGS = {"m1": ["dream pop"], "m10": ["dream pop", "shoegaze"], "m20": ["jazz"]}


def make(deezer_fail: bool = False) -> Recommender:
    return Recommender(
        FakeDeezer(ARTISTS, RELATED, fail=deezer_fail),
        FakeListenBrainz(SIMILAR, TAGS),
        FakeMusicBrainz(MBIDS),
    )


async def test_recommends_unknown_neighbors_with_reasons_and_previews():
    result = await make().recommend(RecRequest(seeds=[1, 2]))
    names = [r.name for r in result.recs]
    assert "Seed One" not in names and "Seed Two" not in names
    assert names[0] == "Shared Neighbor"
    top = result.recs[0]
    assert set(top.because) == {"Seed One", "Seed Two"}
    assert top.sources == ["deezer", "listenbrainz"]
    assert top.shared_tags == ["dream pop"]
    assert top.track is not None and top.track.preview
    assert [s.name for s in result.seeds] == ["Seed One", "Seed Two"]
    assert result.warnings == []


async def test_artists_missing_from_deezer_are_dropped():
    result = await make().recommend(RecRequest(seeds=[1]))
    assert "Not On Deezer" not in [r.name for r in result.recs]
    assert "LB Only" in [r.name for r in result.recs]


async def test_adventurous_slider_moves_famous_artist_down():
    familiar = await make().recommend(RecRequest(seeds=[1, 2], adventurousness=0.0))
    adventurous = await make().recommend(RecRequest(seeds=[1, 2], adventurousness=1.0))

    def rank(res):
        return [r.name for r in res.recs].index("Famous")

    assert rank(adventurous) > rank(familiar)


async def test_excluded_and_skipped_artists_never_appear():
    result = await make().recommend(
        RecRequest(seeds=[1, 13], skipped=[11], exclude_names=["the famous"])
    )
    names = [r.name for r in result.recs]
    assert "Only Deezer" not in names
    assert "Famous" not in names


async def test_liked_rec_becomes_a_positive_anchor():
    result = await make().recommend(RecRequest(seeds=[1], liked=[10]))
    assert "Shared Neighbor" not in [r.name for r in result.recs]


async def test_unknown_seeds_raise_and_partial_seeds_warn():
    with pytest.raises(NoSeedsError):
        await make().recommend(RecRequest(seeds=[999]))
    result = await make().recommend(RecRequest(seeds=[1, 999]))
    assert result.recs and result.warnings


async def test_deezer_outage_falls_back_to_listenbrainz_with_warning():
    result = await make(deezer_fail=True).recommend(RecRequest(seeds=[1]))
    assert [r.name for r in result.recs][:1] == ["Shared Neighbor"]
    assert any("Deezer" in w for w in result.warnings)


async def test_limit_is_respected():
    result = await make().recommend(RecRequest(seeds=[1, 2], limit=2))
    assert len(result.recs) == 2
