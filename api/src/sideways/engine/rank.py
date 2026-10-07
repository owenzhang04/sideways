"""Ranking: personalized PageRank, popularity adjustment, steering, MMR diversity."""

import math
from dataclasses import dataclass, field

import networkx as nx

from sideways.engine.graph import ArtistGraph

DAMPING = 0.85
# How much the negative (skipped) walk is subtracted from the positive one.
NEGATIVE_FACTOR = 0.5
# Score change per 10x fans at the ends of the familiar <-> adventurous slider.
POPULARITY_BETA = 1.2
# Strong enough that a clear request can reorder the list, not just nudge it.
STEER_WEIGHT = 0.6
MMR_LAMBDA = 0.75
_EPS = 1e-12


def personalized_pagerank(graph: nx.Graph, seeds: dict[str, float]) -> dict[str, float]:
    seeds = {k: w for k, w in seeds.items() if k in graph and w > 0}
    if not seeds or graph.number_of_edges() == 0:
        return {}
    return nx.pagerank(graph, alpha=DAMPING, personalization=seeds, weight="weight")


def walk_scores(
    graph: ArtistGraph, positive: dict[str, float], negative: dict[str, float]
) -> dict[str, float]:
    g = graph.to_networkx()
    pos = personalized_pagerank(g, positive)
    neg = personalized_pagerank(g, negative)
    return {k: v - NEGATIVE_FACTOR * neg.get(k, 0.0) for k, v in pos.items()}


def popularity_adjusted(walk: float, fans: int | None, adventurousness: float) -> float:
    """log(walk mass) shifted by popularity.

    adventurousness 0 favors well-known artists, 1 favors obscure ones, 0.5 is neutral.
    Unknown fan counts are treated as neutral.
    """
    base = math.log(max(walk, _EPS))
    if fans is None:
        return base
    tilt = (0.5 - adventurousness) * 2 * POPULARITY_BETA
    return base + tilt * math.log10(fans + 10)


def min_max(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi - lo < _EPS:
        return {k: 1.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


def blend_steer(base: float, match: float | None) -> float:
    """base is a normalized score in [0, 1]; the steer match shifts it around 0.5."""
    if match is None:
        return base
    return base + STEER_WEIGHT * (match - 0.5) * 2


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def mmr(scores: dict[str, float], tags: dict[str, set[str]], k: int) -> list[str]:
    """Maximal marginal relevance: trade score against tag overlap with already-picked items."""
    norm = min_max(scores)
    remaining = set(norm)
    picked: list[str] = []
    while remaining and len(picked) < k:

        def value(key: str) -> float:
            overlap = max(
                (jaccard(tags.get(key, set()), tags.get(p, set())) for p in picked), default=0
            )
            return MMR_LAMBDA * norm[key] - (1 - MMR_LAMBDA) * overlap

        best = max(sorted(remaining), key=value)
        picked.append(best)
        remaining.remove(best)
    return picked


@dataclass
class Explanation:
    because: list[str] = field(default_factory=list)
    via: str | None = None
    sources: list[str] = field(default_factory=list)


def explain(graph: ArtistGraph, key: str, anchors: dict[str, float]) -> Explanation:
    """Which anchor artists send this candidate the most weight, and through which sources."""
    direct = []
    sources: set[str] = set()
    for anchor, weight in anchors.items():
        edge = graph.edge(anchor, key)
        if edge is not None:
            direct.append((edge.weight * weight, anchor))
            sources.update(edge.by_source)
    if direct:
        direct.sort(reverse=True)
        names = [graph.nodes[a].name for _, a in direct[:3]]
        return Explanation(because=names, sources=sorted(sources))

    best: tuple[float, str] | None = None
    for mid in graph.neighbors(key):
        to_anchor = max((_edge_weight(graph, mid, a) * w for a, w in anchors.items()), default=0)
        strength = to_anchor * _edge_weight(graph, mid, key)
        if to_anchor > 0 and (best is None or strength > best[0]):
            best = (strength, mid)
    if best is None:
        return Explanation()
    mid = best[1]
    anchor_names = [graph.nodes[a].name for a in anchors if graph.edge(mid, a) is not None]
    edge = graph.edge(mid, key)
    return Explanation(
        because=anchor_names[:2],
        via=graph.nodes[mid].name,
        sources=sorted(edge.by_source) if edge else [],
    )


def _edge_weight(graph: ArtistGraph, a: str, b: str) -> float:
    edge = graph.edge(a, b)
    return edge.weight if edge else 0.0
