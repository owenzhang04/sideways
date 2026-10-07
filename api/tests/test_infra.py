import asyncio
import time

import httpx
import pytest
import respx

from sideways.cache import Cache
from sideways.http import Upstream, UpstreamError
from sideways.sessions import Sessions
from sideways.sources.deezer import Deezer
from sideways.sources.spotify import Token, weigh_artists

URL = "https://api.example/x"
_real_sleep = asyncio.sleep


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c


@respx.mock
async def test_retries_transient_errors_then_succeeds(client, monkeypatch):
    monkeypatch.setattr("sideways.http.asyncio.sleep", _no_sleep)
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(429), httpx.Response(200, json={"ok": 1})]
    )
    up = Upstream("t", client, None, per_second=1000)
    assert await up.get_json(URL) == {"ok": 1}
    assert route.call_count == 3


@respx.mock
async def test_gives_up_after_attempts_and_does_not_retry_client_errors(client, monkeypatch):
    monkeypatch.setattr("sideways.http.asyncio.sleep", _no_sleep)
    respx.get(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(UpstreamError, match="unavailable"):
        await Upstream("t", client, None, per_second=1000).get_json(URL)
    route = respx.get(URL + "/404").mock(return_value=httpx.Response(404, text="missing"))
    with pytest.raises(UpstreamError, match="404"):
        await Upstream("t", client, None, per_second=1000).get_json(URL + "/404")
    assert route.call_count == 1


@respx.mock
async def test_cached_get_skips_network(client, tmp_path):
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=[1, 2]))
    up = Upstream("t", client, Cache(tmp_path / "c.db"), per_second=1000)
    assert await up.get_json(URL, {"a": 1}, ttl=60) == [1, 2]
    assert await up.get_json(URL, {"a": 1}, ttl=60) == [1, 2]
    assert route.call_count == 1


@respx.mock
async def test_deezer_error_object_in_200_raises(client):
    respx.get("https://api.deezer.com/artist/1").mock(
        return_value=httpx.Response(200, json={"error": {"code": 800, "message": "no data"}})
    )
    with pytest.raises(UpstreamError, match="800"):
        await Deezer(Upstream("deezer", client, None, per_second=1000)).artist(1)


def test_cache_expiry(tmp_path):
    cache = Cache(tmp_path / "c.db")
    cache.set("k", {"v": 1}, ttl=-1)
    assert cache.get("k") is None
    assert cache.purge_expired() == 1
    assert cache.get("missing") is None


def test_sessions_store_only_hashes_and_expire(tmp_path):
    sessions = Sessions(tmp_path / "s.db")
    raw = sessions.create(Token("acc", "ref", time.time() + 3600))
    stored = sessions._db.execute("SELECT id FROM sessions").fetchone()[0]
    assert stored != raw and raw not in stored
    assert sessions.get(raw).access == "acc"
    assert sessions.get(stored) is None
    assert sessions.get(None) is None
    sessions._db.execute("UPDATE sessions SET created = 0")
    assert sessions.get(raw) is None


def test_oauth_state_is_single_use(tmp_path):
    sessions = Sessions(tmp_path / "s.db")
    sessions.save_state("st", "ver")
    assert sessions.pop_state("st") == "ver"
    assert sessions.pop_state("st") is None
    assert sessions.pop_state("never") is None


def test_weigh_artists_prefers_recent_top_artists_and_tracks_known():
    taste = weigh_artists(
        {
            "short_term": [{"name": "Now"}],
            "long_term": [{"name": "Old"}, {"name": "Older"}],
        },
        saved=[{"artists": [{"name": "Saved"}]}],
        recent=[{"artists": [{"name": "Now"}, {"name": "Feature"}]}],
    )
    assert taste.ranked[0] == "Now"
    assert taste.ranked.index("Old") < taste.ranked.index("Saved")
    assert taste.known == {"Now", "Old", "Older", "Saved", "Feature"}
    assert weigh_artists({}, [], []).ranked == []


async def _no_sleep(_seconds):
    await _real_sleep(0)
