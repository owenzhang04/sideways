"""In-memory stand-ins for the external music services."""

from sideways.http import UpstreamError
from sideways.names import norm_name
from sideways.sources.deezer import DeezerArtist, DeezerTrack
from sideways.sources.listenbrainz import SimilarArtist


def artist(i: int, name: str, fans: int = 1000) -> DeezerArtist:
    return DeezerArtist(id=i, name=name, fans=fans, picture=f"pic{i}")


class FakeDeezer:
    def __init__(
        self, artists: list[DeezerArtist], related: dict[int, list[int]], fail: bool = False
    ) -> None:
        self.by_id = {a.id: a for a in artists}
        self.related_ids = related
        self.fail = fail

    async def artist(self, artist_id: int) -> DeezerArtist:
        if artist_id not in self.by_id:
            raise UpstreamError(f"deezer: no artist {artist_id}")
        return self.by_id[artist_id]

    async def related(self, artist_id: int) -> list[DeezerArtist]:
        if self.fail:
            raise UpstreamError("deezer down")
        return [self.by_id[i] for i in self.related_ids.get(artist_id, [])]

    async def search_artists(self, query: str, limit: int = 8) -> list[DeezerArtist]:
        return [a for a in self.by_id.values() if query.lower() in a.name.lower()][:limit]

    async def find_artist(self, name: str) -> DeezerArtist | None:
        matches = [a for a in self.by_id.values() if norm_name(a.name) == norm_name(name)]
        return max(matches, key=lambda a: a.fans, default=None)

    async def top_tracks(self, artist_id: int, limit: int = 5) -> list[DeezerTrack]:
        return [DeezerTrack(artist_id * 10, f"song {artist_id}", "prev.mp3", "alb", "c", "l", 200)]

    async def track_isrc(self, track_id: int) -> str | None:
        return f"ISRC{track_id}"


class FakeListenBrainz:
    def __init__(self, similar: dict[str, list[tuple[str, str, float]]], tags=None) -> None:
        self.similar = similar
        self.tags = tags or {}

    async def similar_artists(self, mbid: str, limit: int = 50) -> list[SimilarArtist]:
        return [SimilarArtist(m, n, s) for m, n, s in self.similar.get(mbid, [])][:limit]

    async def artist_tags(self, mbids: list[str], per_artist: int = 8) -> dict[str, list[str]]:
        return {m: self.tags[m] for m in mbids if m in self.tags}


class FakeMusicBrainz:
    def __init__(self, mbids: dict[str, str]) -> None:
        self.mbids = mbids

    async def find_mbid(self, name: str) -> str | None:
        return self.mbids.get(name)
