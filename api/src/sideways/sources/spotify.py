"""Spotify: OAuth (authorization code + PKCE), taste extraction, playlist save.

Development Mode apps (Feb 2026 rules) can still read top items, saved tracks and
recently played, search (max 10 per page), and create playlists via POST /me/playlists.
Related artists, top tracks and popularity are gone, which is why similarity comes
from ListenBrainz and Deezer instead.
"""

import base64
import hashlib
import secrets
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from sideways.engine.graph import rank_weights
from sideways.http import Upstream, UpstreamError

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
SCOPES = "user-top-read user-library-read user-read-recently-played playlist-modify-private"
RANGE_WEIGHTS = {"short_term": 3.0, "medium_term": 2.0, "long_term": 1.0}
SAVED_TRACK_WEIGHT = 0.5
RECENT_PLAY_WEIGHT = 0.3
SAVED_TRACK_PAGES = 4


@dataclass
class Token:
    access: str
    refresh: str
    expires_at: float

    @property
    def stale(self) -> bool:
        return time.time() > self.expires_at - 60


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class SpotifyAuth:
    def __init__(self, upstream: Upstream, client_id: str, secret: str, redirect: str) -> None:
        self.up = upstream
        self.client_id = client_id
        self.redirect_uri = redirect
        basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
        self._headers = {"Authorization": f"Basic {basic}"}

    def authorize_url(self, state: str, challenge: str) -> str:
        query = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
        return f"{AUTH_URL}?{urlencode(query)}"

    async def exchange(self, code: str, verifier: str) -> Token:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": verifier,
        }
        return self._token(await self._post(form), refresh="")

    async def refresh(self, token: Token) -> Token:
        form = {"grant_type": "refresh_token", "refresh_token": token.refresh}
        return self._token(await self._post(form), refresh=token.refresh)

    async def _post(self, form: dict[str, str]) -> dict[str, Any]:
        return await self.up.request("POST", TOKEN_URL, data=form, headers=self._headers)

    @staticmethod
    def _token(data: dict[str, Any], refresh: str) -> Token:
        return Token(
            access=data["access_token"],
            # Spotify may omit refresh_token on refresh; keep the old one.
            refresh=data.get("refresh_token") or refresh,
            expires_at=time.time() + int(data.get("expires_in", 3600)),
        )


class SpotifyUser:
    """API calls on behalf of one logged-in user. Refreshes the token when stale."""

    def __init__(self, upstream: Upstream, auth: SpotifyAuth, token: Token) -> None:
        self.up = upstream
        self.auth = auth
        self.token = token
        self.refreshed = False

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        if self.token.stale:
            self.token = await self.auth.refresh(self.token)
            self.refreshed = True
        headers = {"Authorization": f"Bearer {self.token.access}"}
        return await self.up.request(method, f"{API}{path}", headers=headers, **kwargs)

    async def top_artists(self, time_range: str) -> list[dict]:
        data = await self._call(
            "GET", "/me/top/artists", params={"limit": 50, "time_range": time_range}
        )
        return data.get("items", [])

    async def saved_tracks(self) -> list[dict]:
        items: list[dict] = []
        for page in range(SAVED_TRACK_PAGES):
            data = await self._call("GET", "/me/tracks", params={"limit": 50, "offset": page * 50})
            items += [i["track"] for i in data.get("items", []) if i.get("track")]
            if not data.get("next"):
                break
        return items

    async def recently_played(self) -> list[dict]:
        data = await self._call("GET", "/me/player/recently-played", params={"limit": 50})
        return [i["track"] for i in data.get("items", []) if i.get("track")]

    async def find_track_uri(self, isrc: str | None, title: str, artist: str) -> str | None:
        queries = [f"isrc:{isrc}"] if isrc else []
        queries.append(f'track:"{title}" artist:"{artist}"')
        for q in queries:
            data = await self._call("GET", "/search", params={"q": q, "type": "track", "limit": 1})
            items = data.get("tracks", {}).get("items", [])
            if items:
                return items[0]["uri"]
        return None

    async def create_playlist(self, name: str, description: str, uris: list[str]) -> str:
        playlist = await self._call(
            "POST",
            "/me/playlists",
            json={"name": name, "description": description, "public": False},
        )
        for i in range(0, len(uris), 100):
            await self._call(
                "POST", f"/playlists/{playlist['id']}/items", json={"uris": uris[i : i + 100]}
            )
        return playlist.get("external_urls", {}).get("spotify", "")


@dataclass
class Taste:
    ranked: list[str]
    known: set[str]


def weigh_artists(
    top_by_range: dict[str, list[dict]], saved: list[dict], recent: list[dict]
) -> Taste:
    """Rank artist names by how central they are to the user's listening."""
    weights: Counter[str] = Counter()
    for time_range, artists in top_by_range.items():
        scale = RANGE_WEIGHTS.get(time_range, 1.0)
        for artist, w in zip(artists, rank_weights(len(artists)), strict=True):
            weights[artist["name"]] += scale * w
    for weight, tracks in ((SAVED_TRACK_WEIGHT, saved), (RECENT_PLAY_WEIGHT, recent)):
        for track in tracks:
            for artist in track.get("artists", []):
                weights[artist["name"]] += weight
    return Taste(ranked=[n for n, _ in weights.most_common()], known=set(weights))


async def fetch_taste(user: SpotifyUser) -> Taste:
    top = {r: await user.top_artists(r) for r in RANGE_WEIGHTS}
    try:
        recent = await user.recently_played()
    except UpstreamError:
        recent = []
    return weigh_artists(top, await user.saved_tracks(), recent)
