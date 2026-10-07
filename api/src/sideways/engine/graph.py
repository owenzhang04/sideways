"""Artist similarity graph merged from several sources, keyed by normalized name.

ListenBrainz identifies artists by MBID, Deezer by numeric ID, and neither knows the
other's IDs, so nodes merge on MBID when both sides have one and on normalized name
otherwise.
"""

from dataclasses import dataclass, field

import networkx as nx

from sideways.names import norm_name

SOURCE_WEIGHT = {"listenbrainz": 0.6, "deezer": 0.4}
# Two independent sources agreeing on an edge is stronger evidence than either alone.
AGREEMENT_BONUS = 0.25


@dataclass
class Node:
    key: str
    name: str
    mbid: str | None = None
    deezer_id: int | None = None
    fans: int | None = None
    picture: str = ""


@dataclass
class Edge:
    by_source: dict[str, float] = field(default_factory=dict)

    @property
    def weight(self) -> float:
        total = sum(SOURCE_WEIGHT[s] * w for s, w in self.by_source.items())
        if len(self.by_source) > 1:
            total += AGREEMENT_BONUS
        return total


class ArtistGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple[str, str], Edge] = {}
        self._mbid_to_key: dict[str, str] = {}

    def add_artist(
        self,
        name: str,
        *,
        mbid: str | None = None,
        deezer_id: int | None = None,
        fans: int | None = None,
        picture: str = "",
    ) -> str:
        key = self._mbid_to_key.get(mbid) if mbid else None
        key = key or norm_name(name) or name
        node = self.nodes.setdefault(key, Node(key=key, name=name))
        if mbid and not node.mbid:
            node.mbid = mbid
            self._mbid_to_key[mbid] = key
        # Deezer has duplicate profiles for many artists; the real one has the most fans.
        if deezer_id and (not node.deezer_id or (fans or 0) > (node.fans or 0)):
            node.deezer_id, node.fans = deezer_id, fans
            node.picture = picture or node.picture
        node.picture = node.picture or picture
        return key

    def add_edge(self, a: str, b: str, source: str, weight: float) -> None:
        if a == b:
            return
        pair = (a, b) if a < b else (b, a)
        edge = self.edges.setdefault(pair, Edge())
        edge.by_source[source] = max(edge.by_source.get(source, 0.0), weight)

    def edge(self, a: str, b: str) -> Edge | None:
        return self.edges.get((a, b) if a < b else (b, a))

    def neighbors(self, key: str) -> list[str]:
        return [b if a == key else a for (a, b) in self.edges if key in (a, b)]

    def to_networkx(self) -> nx.Graph:
        g = nx.Graph()
        g.add_nodes_from(self.nodes)
        g.add_weighted_edges_from((a, b, e.weight) for (a, b), e in self.edges.items())
        return g


def rank_weights(n: int) -> list[float]:
    """Linear decay from 1.0 for sources that give an ordered list without scores."""
    return [1.0 - i / (n + 1) for i in range(n)]


def score_weights(scores: list[float]) -> list[float]:
    """Scale raw similarity scores into (0, 1] relative to the strongest neighbor."""
    top = max(scores, default=0.0)
    return [s / top if top > 0 else 0.0 for s in scores]
