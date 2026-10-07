"""HTTP API, plus the built web app in production."""

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typesafe_sdk import AsyncTypeSafeClient

from sideways.cache import Cache
from sideways.config import Settings, settings
from sideways.engine.jev import JevRanker
from sideways.engine.pipeline import NoSeedsError, Recommender, RecRequest, RecResult
from sideways.http import Upstream, UpstreamError
from sideways.sessions import Sessions
from sideways.sources.deezer import Deezer, DeezerArtist
from sideways.sources.listenbrainz import ListenBrainz
from sideways.sources.musicbrainz import MusicBrainz
from sideways.sources.spotify import SpotifyAuth, SpotifyUser, fetch_taste, pkce_pair

log = logging.getLogger(__name__)

SESSION_COOKIE = "sideways_session"
STATE_COOKIE = "sideways_oauth"
SPOTIFY_SEEDS = 10
SPOTIFY_CANDIDATE_SEEDS = 20
KNOWN_NAMES_LIMIT = 400


class IpLimiter:
    """Fixed-window per-IP limit on expensive endpoints of a public site."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, tuple[int, int]] = {}

    def allow(self, ip: str) -> bool:
        window = int(time.time() // 60)
        start, count = self._hits.get(ip, (window, 0))
        if start != window:
            start, count = window, 0
        self._hits[ip] = (start, count + 1)
        if len(self._hits) > 10_000:
            self._hits = {k: v for k, v in self._hits.items() if v[0] == window}
        return count < self.per_minute


@dataclass
class Services:
    settings: Settings
    deezer: Deezer
    recommender: Recommender
    sessions: Sessions
    spotify_auth: SpotifyAuth | None
    spotify_api: Upstream | None
    limiter: IpLimiter


@asynccontextmanager
async def build_services(s: Settings) -> AsyncGenerator[Services]:
    cache = Cache(s.data_dir / "cache.db")
    headers = {"User-Agent": s.user_agent}
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        # Deezer allows 50 requests per 5 s.
        deezer = Deezer(Upstream("deezer", client, cache, per_second=9))
        lb = ListenBrainz(
            labs=Upstream("lb-labs", client, cache, per_second=3),
            api=Upstream("lb-api", client, cache, per_second=2),
        )
        mb = MusicBrainz(Upstream("musicbrainz", client, cache, per_second=1))
        jev_client = AsyncTypeSafeClient(api_key=s.typesafe_api_key) if s.jev_enabled else None
        jev = JevRanker(jev_client, s.jev_model) if jev_client else None
        auth = None
        if s.spotify_enabled:
            auth = SpotifyAuth(
                Upstream("spotify-auth", client, None, per_second=5),
                s.spotify_client_id,
                s.spotify_client_secret,
                s.spotify_redirect_uri,
            )
        try:
            yield Services(
                settings=s,
                deezer=deezer,
                recommender=Recommender(deezer, lb, mb, jev),
                sessions=Sessions(s.data_dir / "sessions.db"),
                spotify_auth=auth,
                spotify_api=Upstream("spotify", client, None, per_second=5) if auth else None,
                limiter=IpLimiter(per_minute=20),
            )
        finally:
            if jev_client:
                await jev_client.aclose()
            cache.close()


def create_app(s: Settings = settings, factory=build_services) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with factory(s) as services:
            app.state.services = services
            yield

    app = FastAPI(
        title="Sideways", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.include_router(router)
    _mount_web(app, s)
    return app


def get_services(request: Request) -> Services:
    return request.app.state.services


Svc = Annotated[Services, Depends(get_services)]
router = APIRouter()


def require_same_origin(request: Request, svc: Svc) -> None:
    """CSRF guard for state-changing requests: the Origin header must be one we serve."""
    origin = (request.headers.get("origin") or "").rstrip("/")
    if origin not in svc.settings.allowed_origins:
        raise HTTPException(403, "Cross-origin request refused.")


# ── Recommendation API ────────────────────────────────────────────────


class ArtistOut(BaseModel):
    deezer_id: int
    name: str
    picture: str
    fans: int


class RecommendIn(BaseModel):
    seeds: list[int] = Field(min_length=1, max_length=25)
    liked: list[int] = Field(default_factory=list, max_length=50)
    skipped: list[int] = Field(default_factory=list, max_length=50)
    exclude_names: list[str] = Field(default_factory=list, max_length=KNOWN_NAMES_LIMIT)
    adventurousness: float = Field(0.5, ge=0, le=1)
    steer: str = Field("", max_length=200)
    limit: int = Field(20, ge=1, le=40)


def _artist_out(a: DeezerArtist) -> ArtistOut:
    return ArtistOut(deezer_id=a.id, name=a.name, picture=a.picture, fans=a.fans)


@router.get("/api/config")
async def config(svc: Svc) -> dict:
    return {
        "spotify_login": svc.spotify_auth is not None,
        "jev": svc.recommender.jev is not None,
    }


@router.get("/api/artists/search")
async def search_artists(
    svc: Svc, q: Annotated[str, Query(min_length=1, max_length=100)]
) -> list[ArtistOut]:
    try:
        return [_artist_out(a) for a in await svc.deezer.search_artists(q)]
    except UpstreamError as e:
        raise HTTPException(502, "Artist search is unavailable right now.") from e


@router.get("/api/tracks/{track_id}/preview")
async def track_preview(track_id: int, svc: Svc) -> dict:
    """Fresh signed preview URL, for when a page outlives the one it was given."""
    try:
        return {"preview": await svc.deezer.track_preview(track_id)}
    except UpstreamError as e:
        raise HTTPException(502, "Preview unavailable right now.") from e


@router.post("/api/recommend", dependencies=[Depends(require_same_origin)])
async def recommend(body: RecommendIn, request: Request, svc: Svc) -> RecResult:
    ip = request.client.host if request.client else "unknown"
    if not svc.limiter.allow(ip):
        raise HTTPException(429, "Too many requests. Wait a minute and try again.")
    req = RecRequest(**body.model_dump())
    try:
        return await svc.recommender.recommend(req)
    except NoSeedsError as e:
        raise HTTPException(422, str(e)) from e
    except UpstreamError as e:
        raise HTTPException(502, "A music data service is unavailable. Try again shortly.") from e


# ── Spotify ───────────────────────────────────────────────────────────


def _spotify_user(request: Request, svc: Svc) -> tuple[SpotifyUser, str]:
    raw = request.cookies.get(SESSION_COOKIE)
    token = svc.sessions.get(raw)
    if svc.spotify_auth is None or svc.spotify_api is None:
        raise HTTPException(404, "Spotify login isn't enabled on this server.")
    if token is None or raw is None:
        raise HTTPException(401, "Log in with Spotify first.")
    return SpotifyUser(svc.spotify_api, svc.spotify_auth, token), raw


def _persist_refresh(svc: Services, user: SpotifyUser, raw: str) -> None:
    if user.refreshed:
        svc.sessions.update(raw, user.token)


class PlaylistTrack(BaseModel):
    deezer_track_id: int
    title: str = Field(max_length=300)
    artist: str = Field(max_length=300)


class PlaylistIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    tracks: list[PlaylistTrack] = Field(min_length=1, max_length=40)


@router.get("/api/spotify/login")
async def login(svc: Svc) -> RedirectResponse:
    if svc.spotify_auth is None:
        raise HTTPException(404, "Spotify login isn't enabled on this server.")
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    svc.sessions.save_state(state, verifier)
    resp = RedirectResponse(svc.spotify_auth.authorize_url(state, challenge))
    _set_cookie(resp, svc.settings, STATE_COOKIE, state, max_age=600)
    return resp


async def callback(request: Request, svc: Svc) -> RedirectResponse:
    return await _finish_login(request, svc)


# v1 registered /callback as the redirect URI; keep it working.
router.add_api_route("/api/spotify/callback", callback, methods=["GET"])
router.add_api_route("/callback", callback, methods=["GET"], include_in_schema=False)


@router.post("/api/spotify/logout", dependencies=[Depends(require_same_origin)])
async def logout(request: Request, response: Response, svc: Svc) -> dict:
    svc.sessions.delete(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/api/spotify/me")
async def me(request: Request, svc: Svc) -> dict:
    return {"logged_in": svc.sessions.get(request.cookies.get(SESSION_COOKIE)) is not None}


@router.get("/api/spotify/seeds")
async def spotify_seeds(request: Request, svc: Svc) -> dict:
    user, raw = _spotify_user(request, svc)
    try:
        taste = await fetch_taste(user)
    except UpstreamError as e:
        raise HTTPException(502, "Spotify didn't respond. Try again shortly.") from e
    finally:
        _persist_refresh(svc, user, raw)
    found = await asyncio.gather(
        *(svc.deezer.find_artist(n) for n in taste.ranked[:SPOTIFY_CANDIDATE_SEEDS]),
        return_exceptions=True,
    )
    seeds = [_artist_out(a) for a in found if isinstance(a, DeezerArtist)][:SPOTIFY_SEEDS]
    return {"seeds": seeds, "known": taste.ranked[:KNOWN_NAMES_LIMIT]}


@router.post("/api/spotify/playlist", dependencies=[Depends(require_same_origin)])
async def save_playlist(body: PlaylistIn, request: Request, svc: Svc) -> dict:
    user, raw = _spotify_user(request, svc)
    try:
        return await _save_playlist(svc, user, body)
    except UpstreamError as e:
        raise HTTPException(502, "Spotify didn't accept the playlist. Try again shortly.") from e
    finally:
        _persist_refresh(svc, user, raw)


async def _finish_login(request: Request, svc: Svc) -> RedirectResponse:
    if svc.spotify_auth is None:
        raise HTTPException(404, "Spotify login isn't enabled on this server.")
    params = request.query_params
    state = params.get("state", "")
    target = svc.settings.frontend_url
    if params.get("error"):
        return RedirectResponse(f"{target}?spotify=denied")
    cookie_state = request.cookies.get(STATE_COOKIE, "")
    verifier = svc.sessions.pop_state(state) if state else None
    if (
        not state
        or not secrets.compare_digest(state.encode(), cookie_state.encode())
        or verifier is None
    ):
        return RedirectResponse(f"{target}?spotify=expired")
    try:
        token = await svc.spotify_auth.exchange(params.get("code", ""), verifier)
    except UpstreamError:
        log.exception("Spotify token exchange failed")
        return RedirectResponse(f"{target}?spotify=failed")
    resp = RedirectResponse(f"{target}?spotify=connected")
    _set_cookie(resp, svc.settings, SESSION_COOKIE, svc.sessions.create(token), max_age=30 * 86_400)
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp


async def _save_playlist(svc: Services, user: SpotifyUser, body: PlaylistIn) -> dict:
    uris: list[str] = []
    missing: list[str] = []
    for t in body.tracks:
        try:
            isrc = await svc.deezer.track_isrc(t.deezer_track_id)
        except UpstreamError:
            isrc = None
        uri = await user.find_track_uri(isrc, t.title, t.artist)
        if uri:
            uris.append(uri)
        else:
            missing.append(f"{t.artist} - {t.title}")
    if not uris:
        raise HTTPException(422, "None of these tracks could be found on Spotify.")
    url = await user.create_playlist(body.name, "Made with Sideways.", uris)
    return {"url": url, "added": len(uris), "missing": missing}


def _set_cookie(resp: Response, s: Settings, name: str, value: str, max_age: int) -> None:
    resp.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=s.secure_cookies,
        path="/",
    )


# ── Web app ───────────────────────────────────────────────────────────


def _mount_web(app: FastAPI, s: Settings) -> None:
    index = s.web_dist / "index.html"
    if not index.exists():
        return
    app.mount("/assets", StaticFiles(directory=s.web_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (s.web_dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(s.web_dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
