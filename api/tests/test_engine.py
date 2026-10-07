import pytest

from sideways.engine.graph import ArtistGraph, rank_weights, score_weights
from sideways.engine.rank import (
    blend_steer,
    explain,
    min_max,
    mmr,
    popularity_adjusted,
    walk_scores,
)
from sideways.names import norm_name


def test_norm_name_merges_common_variants():
    assert norm_name("The Beatles") == norm_name("beatles")
    assert norm_name("Beyoncé") == norm_name("Beyonce")
    assert norm_name("Simon & Garfunkel") == norm_name("Simon and Garfunkel")
    assert norm_name("!!!") == ""


def test_nodes_merge_by_name_and_then_by_mbid():
    g = ArtistGraph()
    a = g.add_artist("The Cure", deezer_id=1)
    b = g.add_artist("Cure", mbid="m1")
    c = g.add_artist("The Cure (band)", mbid="m1")
    assert a == b == c
    assert g.nodes[a].deezer_id == 1 and g.nodes[a].mbid == "m1"


def test_duplicate_deezer_profiles_keep_the_one_with_more_fans():
    g = ArtistGraph()
    k = g.add_artist("Best Coast", deezer_id=1, fans=31)
    g.add_artist("Best Coast", deezer_id=2, fans=48_713)
    g.add_artist("Best Coast", deezer_id=3, fans=5)
    assert (g.nodes[k].deezer_id, g.nodes[k].fans) == (2, 48_713)


def test_edges_are_undirected_and_agreement_outweighs_one_source():
    g = ArtistGraph()
    g.add_edge("a", "b", "deezer", 1.0)
    g.add_edge("b", "a", "listenbrainz", 1.0)
    g.add_edge("a", "c", "listenbrainz", 1.0)
    g.add_edge("a", "a", "deezer", 1.0)
    assert len(g.edges) == 2
    assert g.edge("b", "a").weight > g.edge("a", "c").weight


def test_weight_helpers_handle_empty_and_zero():
    assert rank_weights(0) == []
    assert rank_weights(3)[0] > rank_weights(3)[-1] > 0
    assert score_weights([]) == []
    assert score_weights([0, 0]) == [0.0, 0.0]
    assert score_weights([5, 10]) == [0.5, 1.0]


def _chain_graph() -> ArtistGraph:
    g = ArtistGraph()
    for name in ["seed", "near", "far", "skip", "skipnear"]:
        g.add_artist(name)
    g.add_edge("seed", "near", "deezer", 1.0)
    g.add_edge("near", "far", "deezer", 1.0)
    g.add_edge("skip", "skipnear", "deezer", 1.0)
    g.add_edge("seed", "skipnear", "deezer", 1.0)
    return g


def test_walk_ranks_closer_artists_higher():
    scores = walk_scores(_chain_graph(), {"seed": 1.0}, {})
    assert scores["near"] > scores["far"] > 0


def test_skipped_artist_pushes_down_its_neighbors():
    g = _chain_graph()
    before = walk_scores(g, {"seed": 1.0}, {})
    after = walk_scores(g, {"seed": 1.0}, {"skip": 1.0})
    drop = {k: 1 - after[k] / before[k] for k in ("skipnear", "near")}
    assert drop["skipnear"] > drop["near"]


def test_walk_with_no_edges_or_unknown_seeds_is_empty():
    g = ArtistGraph()
    g.add_artist("lonely")
    assert walk_scores(g, {"lonely": 1.0}, {}) == {}
    assert walk_scores(_chain_graph(), {"missing": 1.0}, {}) == {}


def test_slider_ends_flip_preference_between_famous_and_obscure():
    famous, obscure = 5_000_000, 5_000
    assert popularity_adjusted(0.01, famous, 0.0) > popularity_adjusted(0.01, obscure, 0.0)
    assert popularity_adjusted(0.01, famous, 1.0) < popularity_adjusted(0.01, obscure, 1.0)
    assert popularity_adjusted(0.01, famous, 0.5) == popularity_adjusted(0.01, obscure, 0.5)
    assert popularity_adjusted(0.01, None, 1.0) == popularity_adjusted(0.01, None, 0.0)
    assert popularity_adjusted(0.0, 10, 0.5) < popularity_adjusted(1e-6, 10, 0.5)


def test_min_max_handles_empty_and_flat():
    assert min_max({}) == {}
    assert min_max({"a": 3, "b": 3}) == {"a": 1.0, "b": 1.0}


def test_steer_blend_is_neutral_at_half_and_can_overturn_a_lead():
    assert blend_steer(0.5, None) == pytest.approx(0.5)
    assert blend_steer(0.5, 0.5) == pytest.approx(0.5)
    assert blend_steer(1.0, 0.0) < blend_steer(0.5, 1.0)


def test_mmr_trades_score_for_tag_diversity():
    scores = {"a": 1.0, "b": 0.95, "c": 0.9, "floor": 0.0}
    tags = {"a": {"shoegaze"}, "b": {"shoegaze"}, "c": {"jazz"}}
    assert mmr(scores, tags, 2) == ["a", "c"]
    assert mmr(scores, {}, 3) == ["a", "b", "c"]
    assert mmr({}, {}, 5) == []


def test_explain_names_direct_anchors_then_falls_back_to_via():
    g = _chain_graph()
    g.add_edge("seed", "near", "listenbrainz", 1.0)
    direct = explain(g, "near", {"seed": 1.0})
    assert direct.because == ["seed"] and direct.via is None
    assert direct.sources == ["deezer", "listenbrainz"]
    two_hop = explain(g, "far", {"seed": 1.0})
    assert two_hop.via == "near" and two_hop.because == ["seed"]
    g.add_artist("island")
    assert explain(g, "island", {"seed": 1.0}).because == []
