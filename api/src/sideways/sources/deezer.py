"""Deezer public API (no auth): artist search, related artists, top tracks with 30s previews."""

from dataclasses import dataclass
from typing import Any

from sideways.cache import DAY
from sideways.http import Upstream, UpstreamError
from sideways.names import norm_name

BASE = "https://api.deezer.com"


@dataclass(frozen=True)
class DeezerArtist:
    id: int
    name: str
    fans: int
    picture: str

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> DeezerArtist:
        return cls(
            id=int(raw["id"]),
            name=raw["name"],
            fans=int(raw.get("nb_fan") or 0),
            picture=raw.get("picture_medium") or "",
        )


@dataclass(frozen=True)
class DeezerTrack:
    id: int
    title: str
    preview: str
    album: str
    cover: str
    link: str
    duration: int


class Deezer:
    def __init__(self, upstream: Upstream) -> None:
        self.up = upstream

    async def _get(self, path: str, params: dict | None = None, ttl: float = 7 * DAY) -> Any:
        data = await self.up.get_json(f"{BASE}{path}", params=params, ttl=ttl)
        # Deezer reports errors (including quota) as HTTP 200 with an "error" object.
        if isinstance(data, dict) and "error" in data:
            raise UpstreamError(f"deezer {path}: {data['error']}")
        return data

    async def search_artists(self, query: str, limit: int = 8) -> list[DeezerArtist]:
        data = await self._get("/search/artist", {"q": query, "limit": limit}, ttl=3 * DAY)
        return [DeezerArtist.parse(a) for a in data.get("data", [])]

    async def find_artist(self, name: str) -> DeezerArtist | None:
        """Best exact-name match; among homonyms, the one with most fans."""
        target = norm_name(name)
        matches = [
            a for a in await self.search_artists(name, limit=10) if norm_name(a.name) == target
        ]
        return max(matches, key=lambda a: a.fans, default=None)

    async def artist(self, artist_id: int) -> DeezerArtist:
        return DeezerArtist.parse(await self._get(f"/artist/{artist_id}"))

    async def related(self, artist_id: int) -> list[DeezerArtist]:
        data = await self._get(f"/artist/{artist_id}/related", {"limit": 25})
        return [DeezerArtist.parse(a) for a in data.get("data", [])]

    async def top_tracks(self, artist_id: int, limit: int = 5) -> list[DeezerTrack]:
        data = await self._get(f"/artist/{artist_id}/top", {"limit": limit}, ttl=3 * DAY)
        return [
            DeezerTrack(
                id=int(t["id"]),
                title=t.get("title_short") or t["title"],
                preview=t.get("preview") or "",
                album=t.get("album", {}).get("title", ""),
                cover=t.get("album", {}).get("cover_medium", ""),
                link=t.get("link", ""),
                duration=int(t.get("duration") or 0),
            )
            for t in data.get("data", [])
        ]

    async def track_isrc(self, track_id: int) -> str | None:
        data = await self._get(f"/track/{track_id}", ttl=30 * DAY)
        return data.get("isrc") or None
