"""End-to-end recommendation: anchors -> graph -> walk -> score -> diversify -> tracks."""

import asyncio
import logging
from dataclasses import dataclass, field

from sideways.engine.graph import ArtistGraph, Node, rank_weights, score_weights
from sideways.engine.rank import (
    Explanation,
    blend_steer,
    explain,
    min_max,
    mmr,
    popularity_adjusted,
    walk_scores,
)
from sideways.engine.steer import SteerCandidate, SteerScorer
from sideways.http import UpstreamError
from sideways.names import norm_name
from sideways.sources.deezer import Deezer, DeezerArtist, DeezerTrack
from sideways.sources.listenbrainz import ListenBrainz
from sideways.sources.musicbrainz import MusicBrainz

log = logging.getLogger(__name__)

SEED_WEIGHT = 1.0
LIKED_WEIGHT = 0.6
# Non-anchor artists whose own neighbors get fetched (second hop).
EXPANSION_SIZE = 12
# Candidates resolved to Deezer and scored after the walk.
POOL_SIZE = 48
STEER_POOL_SIZE = 40


class NoSeedsError(ValueError):
    pass


@dataclass
class RecRequest:
    seeds: list[int]
    liked: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    exclude_names: list[str] = field(default_factory=list)
    adventurousness: float = 0.5
    steer: str = ""
    limit: int = 20


@dataclass
class SeedOut:
    deezer_id: int
    name: str
    picture: str


@dataclass
class Rec:
    deezer_id: int
    name: str
    picture: str
    fans: int | None
    tags: list[str]
    shared_tags: list[str]
    because: list[str]
    via: str | None
    sources: list[str]
    track: DeezerTrack | None
    walk: float
    steer_match: float | None


@dataclass
class RecResult:
    seeds: list[SeedOut]
    recs: list[Rec]
    warnings: list[str]
    steered: bool


@dataclass
class _Anchors:
    positive: dict[str, float]
    negative: dict[str, float]
    seeds: list[SeedOut]


class Recommender:
    def __init__(
        self, deezer: Deezer, lb: ListenBrainz, mb: MusicBrainz, steer: SteerScorer | None = None
    ) -> None:
        self.deezer = deezer
        self.lb = lb
        self.mb = mb
        self.steer = steer

    async def recommend(self, req: RecRequest) -> RecResult:
        warnings: set[str] = set()
        graph = ArtistGraph()
        anchors = await self._add_anchors(graph, req, warnings)
        anchor_keys = [*anchors.positive, *anchors.negative]
        # MusicBrainz allows 1 req/s, so Deezer neighbors are fetched while MBIDs resolve.
        await asyncio.gather(
            self._resolve_mbids(graph, anchor_keys, warnings),
            *(self._expand_deezer(graph, k, warnings) for k in anchor_keys),
        )
        await asyncio.gather(*(self._expand_lb(graph, k, warnings) for k in anchor_keys))

        walk = walk_scores(graph, anchors.positive, anchors.negative)
        excluded = {*anchors.positive, *anchors.negative, *map(norm_name, req.exclude_names)}
        expansion = _top(walk, excluded, EXPANSION_SIZE)
        await self._expand(graph, expansion, warnings)
        walk = walk_scores(graph, anchors.positive, anchors.negative)

        candidates = _top(walk, excluded, POOL_SIZE)
        pool, tags = await asyncio.gather(
            self._resolve_pool(graph, candidates, warnings),
            self._tags(graph, [*candidates, *anchors.positive], warnings),
        )
        anchor_ids = {graph.nodes[k].deezer_id for k in anchor_keys}
        pool = _dedupe_by_deezer(graph, pool, anchor_ids)
        explanations = {k: explain(graph, k, anchors.positive) for k in pool}

        scores = min_max(
            {
                k: popularity_adjusted(walk[k], graph.nodes[k].fans, req.adventurousness)
                for k in pool
            }
        )
        steer = await self._steer(graph, req.steer, scores, tags, warnings)
        scores = {k: blend_steer(v, steer.get(k)) for k, v in scores.items()}

        order = mmr(scores, {k: set(tags.get(k, [])) for k in pool}, req.limit)
        tracks = await self._tracks(graph, order, warnings)
        seed_tags = {t for k in anchors.positive for t in tags.get(k, [])}
        recs = [
            _build_rec(
                graph.nodes[k],
                tags=tags.get(k, []),
                seed_tags=seed_tags,
                why=explanations[k],
                track=tracks.get(k),
                walk=walk[k],
                steer_match=steer.get(k),
            )
            for k in order
        ]
        return RecResult(anchors.seeds, recs, sorted(warnings), steered=bool(steer))

    async def _add_anchors(
        self, graph: ArtistGraph, req: RecRequest, warnings: set[str]
    ) -> _Anchors:
        roles = [(i, "seed") for i in req.seeds]
        roles += [(i, "liked") for i in req.liked]
        roles += [(i, "skipped") for i in req.skipped]
        artists = await asyncio.gather(
            *(self.deezer.artist(i) for i, _ in roles), return_exceptions=True
        )
        anchors = _Anchors({}, {}, [])
        for (_, role), artist in zip(roles, artists, strict=True):
            if isinstance(artist, BaseException):
                log.warning("Deezer artist lookup failed: %s", artist)
                warnings.add("Some artists couldn't be loaded from Deezer.")
                continue
            key = graph.add_artist(
                artist.name, deezer_id=artist.id, fans=artist.fans, picture=artist.picture
            )
            if role == "seed":
                anchors.positive[key] = SEED_WEIGHT
                anchors.seeds.append(SeedOut(artist.id, artist.name, artist.picture))
            elif role == "liked":
                anchors.positive.setdefault(key, LIKED_WEIGHT)
            else:
                anchors.negative[key] = 1.0
        if not anchors.positive:
            raise NoSeedsError("None of the seed artists could be found.")
        return anchors

    async def _resolve_mbids(self, graph: ArtistGraph, keys: list[str], warnings: set[str]) -> None:
        names = [graph.nodes[k].name for k in keys]
        results = await asyncio.gather(
            *(self.mb.find_mbid(n) for n in names), return_exceptions=True
        )
        for name, mbid in zip(names, results, strict=True):
            if isinstance(mbid, BaseException):
                log.warning("MusicBrainz lookup failed for %s: %s", name, mbid)
                warnings.add("MusicBrainz was unreachable; ListenBrainz data is partial.")
            elif mbid:
                graph.add_artist(name, mbid=mbid)

    async def _expand(self, graph: ArtistGraph, keys: list[str], warnings: set[str]) -> None:
        """Fetch neighbors from every source the node has an ID for, and add the edges."""
        await asyncio.gather(*(self._expand_one(graph, k, warnings) for k in keys))

    async def _expand_one(self, graph: ArtistGraph, key: str, warnings: set[str]) -> None:
        await asyncio.gather(
            self._expand_deezer(graph, key, warnings), self._expand_lb(graph, key, warnings)
        )

    async def _expand_deezer(self, graph: ArtistGraph, key: str, warnings: set[str]) -> None:
        node = graph.nodes[key]
        if not node.deezer_id:
            return
        try:
            related = await self.deezer.related(node.deezer_id)
        except UpstreamError as e:
            log.warning("Deezer related failed for %s: %s", node.name, e)
            warnings.add("Deezer related-artist data was partly unavailable.")
        else:
            _add_deezer_edges(graph, key, related)

    async def _expand_lb(self, graph: ArtistGraph, key: str, warnings: set[str]) -> None:
        node = graph.nodes[key]
        if not node.mbid:
            return
        try:
            similar = await self.lb.similar_artists(node.mbid)
        except UpstreamError as e:
            log.warning("ListenBrainz similar failed for %s: %s", node.name, e)
            warnings.add("ListenBrainz similarity data was partly unavailable.")
        else:
            for s, w in zip(similar, score_weights([s.score for s in similar]), strict=True):
                graph.add_edge(key, graph.add_artist(s.name, mbid=s.mbid), "listenbrainz", w)

    async def _resolve_pool(
        self, graph: ArtistGraph, keys: list[str], warnings: set[str]
    ) -> list[str]:
        """Give every candidate a Deezer ID (needed for tracks and fan counts); drop the rest."""
        missing = [k for k in keys if not graph.nodes[k].deezer_id]
        found = await asyncio.gather(
            *(self.deezer.find_artist(graph.nodes[k].name) for k in missing),
            return_exceptions=True,
        )
        for key, artist in zip(missing, found, strict=True):
            if isinstance(artist, BaseException):
                log.warning("Deezer search failed for %s: %s", graph.nodes[key].name, artist)
                warnings.add("Some candidates were skipped because Deezer search failed.")
            elif isinstance(artist, DeezerArtist):
                node = graph.nodes[key]
                node.deezer_id, node.fans = artist.id, artist.fans
                node.picture = node.picture or artist.picture
        return [k for k in keys if graph.nodes[k].deezer_id]

    async def _tags(
        self, graph: ArtistGraph, keys: list[str], warnings: set[str]
    ) -> dict[str, list[str]]:
        by_mbid = {graph.nodes[k].mbid: k for k in keys if graph.nodes[k].mbid}
        try:
            tags = await self.lb.artist_tags(list(by_mbid))
        except UpstreamError as e:
            log.warning("ListenBrainz tags failed: %s", e)
            warnings.add("Genre tags were unavailable.")
            return {}
        return {by_mbid[m]: t for m, t in tags.items() if m in by_mbid}

    async def _steer(
        self,
        graph: ArtistGraph,
        request: str,
        scores: dict[str, float],
        tags: dict[str, list[str]],
        warnings: set[str],
    ) -> dict[str, float]:
        if self.steer is None or not request.strip():
            return {}
        if self.steer.status == "loading":
            warnings.add("Steering is still warming up; this list ignores your request.")
            return {}
        if self.steer.status != "ready":
            warnings.add("Steering is unavailable right now; this list ignores your request.")
            return {}
        top = sorted(scores, key=lambda k: -scores[k])[:STEER_POOL_SIZE]
        candidates = [SteerCandidate(k, graph.nodes[k].name, tags.get(k, [])) for k in top]
        try:
            return await self.steer.score(request, candidates)
        except Exception:
            log.exception("Steering failed")
            warnings.add("Steering failed; this list ignores your request.")
            return {}

    async def _tracks(
        self, graph: ArtistGraph, keys: list[str], warnings: set[str]
    ) -> dict[str, DeezerTrack]:
        results = await asyncio.gather(
            *(self.deezer.top_tracks(graph.nodes[k].deezer_id or 0) for k in keys),
            return_exceptions=True,
        )
        picked: dict[str, DeezerTrack] = {}
        for key, tracks in zip(keys, results, strict=True):
            if isinstance(tracks, BaseException):
                log.warning("Deezer top tracks failed for %s: %s", graph.nodes[key].name, tracks)
                warnings.add("Some previews couldn't be loaded.")
                continue
            with_preview = [t for t in tracks if t.preview]
            if with_preview or tracks:
                picked[key] = (with_preview or tracks)[0]
        return picked


def _add_deezer_edges(graph: ArtistGraph, key: str, related: list[DeezerArtist]) -> None:
    for artist, weight in zip(related, rank_weights(len(related)), strict=True):
        other = graph.add_artist(
            artist.name, deezer_id=artist.id, fans=artist.fans, picture=artist.picture
        )
        graph.add_edge(key, other, "deezer", weight)


def _top(walk: dict[str, float], excluded: set[str], n: int) -> list[str]:
    ranked = sorted(
        (k for k, v in walk.items() if v > 0 and k not in excluded), key=walk.__getitem__
    )
    return ranked[::-1][:n]


def _dedupe_by_deezer(graph: ArtistGraph, keys: list[str], taken: set[int | None]) -> list[str]:
    """Two name-keyed nodes can resolve to one Deezer artist; keep the higher-ranked one."""
    seen = set(taken)
    out = []
    for key in keys:
        deezer_id = graph.nodes[key].deezer_id
        if deezer_id not in seen:
            seen.add(deezer_id)
            out.append(key)
    return out


def _build_rec(
    node: Node,
    *,
    tags: list[str],
    seed_tags: set[str],
    why: Explanation,
    track: DeezerTrack | None,
    walk: float,
    steer_match: float | None,
) -> Rec:
    return Rec(
        deezer_id=node.deezer_id or 0,
        name=node.name,
        picture=node.picture,
        fans=node.fans,
        tags=tags,
        shared_tags=[t for t in tags if t in seed_tags][:3],
        because=why.because,
        via=why.via,
        sources=why.sources,
        track=track,
        walk=walk,
        steer_match=steer_match,
    )
