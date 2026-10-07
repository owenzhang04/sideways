from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sideways.config import settings
from sideways.engine.pipeline import Recommender
from sideways.main import STATE_COOKIE, IpLimiter, Services, create_app
from sideways.sessions import Sessions
from sideways.sources.spotify import Token
from tests.fakes import FakeDeezer, FakeListenBrainz, FakeMusicBrainz
from tests.test_pipeline import ARTISTS, MBIDS, RELATED, SIMILAR, TAGS

ORIGIN = "http://127.0.0.1:8000"


class FakeAuth:
    def authorize_url(self, state: str, challenge: str) -> str:
        return f"https://accounts.example/authorize?state={state}"

    async def exchange(self, code: str, verifier: str) -> Token:
        assert verifier
        return Token("access", "refresh", 9e12)


def make_client(tmp_path: Path, spotify: bool = False, web_dist: Path | None = None) -> TestClient:
    s = replace(
        settings,
        allowed_origins=(ORIGIN,),
        frontend_url="/",
        data_dir=tmp_path,
        web_dist=web_dist or tmp_path / "no-web",
    )
    deezer = FakeDeezer(ARTISTS, RELATED)

    @asynccontextmanager
    async def factory(_):
        yield Services(
            settings=s,
            deezer=deezer,
            recommender=Recommender(
                deezer, FakeListenBrainz(SIMILAR, TAGS), FakeMusicBrainz(MBIDS)
            ),
            sessions=Sessions(tmp_path / "sessions.db"),
            spotify_auth=FakeAuth() if spotify else None,
            spotify_api=object() if spotify else None,  # type: ignore[arg-type]
            limiter=IpLimiter(per_minute=3),
        )

    return TestClient(create_app(s, factory))


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path) as c:
        yield c


def test_config_reports_disabled_features(client):
    assert client.get("/api/config").json() == {"spotify_login": False, "jev": False}


def test_artist_search_validates_query(client):
    assert client.get("/api/artists/search", params={"q": "seed"}).status_code == 200
    assert client.get("/api/artists/search", params={"q": ""}).status_code == 422
    assert client.get("/api/artists/search", params={"q": "x" * 101}).status_code == 422


def test_recommend_returns_recs_for_same_origin(client):
    resp = client.post("/api/recommend", json={"seeds": [1, 2]}, headers={"Origin": ORIGIN})
    assert resp.status_code == 200
    body = resp.json()
    assert body["recs"][0]["name"] == "Shared Neighbor"
    assert body["recs"][0]["track"]["preview"]


@pytest.mark.parametrize("origin", [None, "https://evil.example", "http://127.0.0.1:8000.evil"])
def test_recommend_refuses_cross_origin(client, origin):
    headers = {"Origin": origin} if origin else {}
    resp = client.post("/api/recommend", json={"seeds": [1]}, headers=headers)
    assert resp.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"seeds": []},
        {"seeds": list(range(26))},
        {"seeds": [1], "adventurousness": 1.5},
        {"seeds": [1], "steer": "x" * 201},
        {"seeds": [1], "limit": 0},
    ],
)
def test_recommend_validates_input(client, body):
    assert client.post("/api/recommend", json=body, headers={"Origin": ORIGIN}).status_code == 422


def test_recommend_unknown_seeds_is_422(client):
    resp = client.post("/api/recommend", json={"seeds": [999]}, headers={"Origin": ORIGIN})
    assert resp.status_code == 422


def test_recommend_is_rate_limited_per_ip(client):
    codes = [
        client.post("/api/recommend", json={"seeds": [1]}, headers={"Origin": ORIGIN}).status_code
        for _ in range(4)
    ]
    assert codes == [200, 200, 200, 429]


def test_track_preview_refresh(client):
    assert client.get("/api/tracks/10/preview").json() == {"preview": "fresh-10.mp3"}
    assert client.get("/api/tracks/11/preview").status_code == 502
    assert client.get("/api/tracks/abc/preview").status_code == 422


def test_spotify_routes_404_when_disabled(client):
    assert client.get("/api/spotify/login", follow_redirects=False).status_code == 404
    assert client.get("/api/spotify/seeds").status_code == 404


def test_spotify_data_requires_login(tmp_path):
    with make_client(tmp_path, spotify=True) as c:
        assert c.get("/api/spotify/seeds").status_code == 401
        assert c.get("/api/spotify/me").json() == {"logged_in": False}


def test_oauth_login_sets_session_and_rejects_replayed_state(tmp_path):
    with make_client(tmp_path, spotify=True) as c:
        login = c.get("/api/spotify/login", follow_redirects=False)
        state = login.headers["location"].split("state=")[1]
        assert c.cookies.get(STATE_COOKIE) == state

        done = c.get(f"/callback?code=abc&state={state}", follow_redirects=False)
        assert done.headers["location"] == "/?spotify=connected"
        assert c.get("/api/spotify/me").json() == {"logged_in": True}

        c.cookies.set(STATE_COOKIE, state)
        replay = c.get(f"/callback?code=abc&state={state}", follow_redirects=False)
        assert replay.headers["location"] == "/?spotify=expired"


def test_oauth_callback_rejects_state_not_matching_cookie(tmp_path):
    with make_client(tmp_path, spotify=True) as c:
        login = c.get("/api/spotify/login", follow_redirects=False)
        state = login.headers["location"].split("state=")[1]
        c.cookies.set(STATE_COOKIE, "attacker-state")
        resp = c.get(f"/api/spotify/callback?code=abc&state={state}", follow_redirects=False)
        assert resp.headers["location"] == "/?spotify=expired"
        assert c.get("/api/spotify/me").json() == {"logged_in": False}


def test_logout_requires_same_origin_and_clears_session(tmp_path):
    with make_client(tmp_path, spotify=True) as c:
        login = c.get("/api/spotify/login", follow_redirects=False)
        state = login.headers["location"].split("state=")[1]
        c.get(f"/callback?code=abc&state={state}", follow_redirects=False)
        assert c.post("/api/spotify/logout").status_code == 403
        assert c.get("/api/spotify/me").json() == {"logged_in": True}
        assert c.post("/api/spotify/logout", headers={"Origin": ORIGIN}).status_code == 200
        assert c.get("/api/spotify/me").json() == {"logged_in": False}


def test_web_app_fallback_serves_index_and_blocks_traversal(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>sideways</html>")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("nope")
    with make_client(tmp_path, web_dist=dist) as c:
        assert "sideways" in c.get("/some/deep/link").text
        assert c.get("/favicon.svg").text == "<svg/>"
        assert "nope" not in c.get("/..%2Fsecret.txt").text
        assert c.get("/api/unknown").status_code == 404


def test_oauth_callback_with_non_ascii_state_is_rejected_not_500(tmp_path):
    with make_client(tmp_path, spotify=True) as c:
        c.cookies.set(STATE_COOKIE, "abc")
        resp = c.get("/callback?code=x&state=%C3%A9t%C3%A9", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "/?spotify=expired"
