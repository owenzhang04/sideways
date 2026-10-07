"""ListenBrainz: session-based similar artists (labs) and batch artist tags (metadata API)."""

from dataclasses import dataclass

from sideways.cache import DAY
from sideways.http import Upstream

LABS = "https://labs.api.listenbrainz.org"
API = "https://api.listenbrainz.org/1"
# The algorithm ListenBrainz's own artist pages use: co-listening within 300s sessions
# over 7,500 days of listens.
SIMILAR_ALGORITHM = (
    "session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30"
)
TAG_BATCH = 25


@dataclass(frozen=True)
class SimilarArtist:
    mbid: str
    name: str
    score: float


class ListenBrainz:
    def __init__(self, labs: Upstream, api: Upstream) -> None:
        self.labs = labs
        self.api = api

    async def similar_artists(self, mbid: str, limit: int = 50) -> list[SimilarArtist]:
        data = await self.labs.get_json(
            f"{LABS}/similar-artists/json",
            {"artist_mbids": mbid, "algorithm": SIMILAR_ALGORITHM},
            ttl=14 * DAY,
        )
        rows = [r for r in data or [] if r.get("artist_mbid") and r.get("artist_mbid") != mbid]
        return [
            SimilarArtist(r["artist_mbid"], r["name"], float(r.get("score") or 0))
            for r in rows[:limit]
        ]

    async def artist_tags(self, mbids: list[str], per_artist: int = 8) -> dict[str, list[str]]:
        """Most-voted tags per artist, fetched in batches."""
        unique = sorted(set(mbids))
        tags: dict[str, list[str]] = {}
        for i in range(0, len(unique), TAG_BATCH):
            batch = unique[i : i + TAG_BATCH]
            data = await self.api.get_json(
                f"{API}/metadata/artist/",
                {"artist_mbids": ",".join(batch), "inc": "tag"},
                ttl=30 * DAY,
            )
            for artist in data or []:
                entries = artist.get("tag", {}).get("artist", [])
                entries = sorted(entries, key=lambda t: -int(t.get("count") or 0))
                tags[artist["artist_mbid"]] = [t["tag"] for t in entries[:per_artist]]
        return tags
