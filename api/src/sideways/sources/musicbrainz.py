"""MusicBrainz name -> MBID lookup. Rate limit is 1 req/s, so results are cached for 30 days."""

from sideways.cache import DAY
from sideways.http import Upstream
from sideways.names import norm_name

BASE = "https://musicbrainz.org/ws/2"
MIN_SCORE = 90


class MusicBrainz:
    def __init__(self, upstream: Upstream) -> None:
        self.up = upstream

    async def find_mbid(self, name: str) -> str | None:
        escaped = name.replace("\\", "\\\\").replace('"', '\\"')
        data = await self.up.get_json(
            f"{BASE}/artist/",
            {"query": f'artist:"{escaped}"', "fmt": "json", "limit": 5},
            ttl=30 * DAY,
        )
        target = norm_name(name)
        for artist in (data or {}).get("artists", []):
            if int(artist.get("score", 0)) >= MIN_SCORE and norm_name(artist["name"]) == target:
                return artist["id"]
        return None
