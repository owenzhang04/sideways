"""Settings from the environment. `.env` at the repo root is loaded for local runs."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")


def _env(*names: str, default: str = "") -> str:
    """First non-empty variable wins. v1 used SPOTIPY_* names, so both spellings work."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    dev: bool
    # Where the OAuth callback sends the browser; "/" when FastAPI serves the built web app.
    frontend_url: str
    # Origins allowed to make state-changing requests (CSRF check).
    allowed_origins: tuple[str, ...]
    data_dir: Path
    web_dist: Path
    user_agent: str

    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str

    typesafe_api_key: str
    jev_model: str

    @property
    def spotify_enabled(self) -> bool:
        return bool(
            self.spotify_client_id and self.spotify_client_secret and self.spotify_redirect_uri
        )

    @property
    def jev_enabled(self) -> bool:
        return bool(self.typesafe_api_key)

    @property
    def secure_cookies(self) -> bool:
        return self.spotify_redirect_uri.startswith("https://")


def load_settings() -> Settings:
    port = int(_env("PORT", default="8000"))
    frontend_url = _env("FRONTEND_URL", default="/")
    redirect = _env("SPOTIFY_REDIRECT_URI", "SPOTIPY_REDIRECT_URI")
    origins = _env("ALLOWED_ORIGINS", default=f"http://127.0.0.1:{port},http://127.0.0.1:5173")
    if redirect:
        parts = urlsplit(redirect)
        origins += f",{parts.scheme}://{parts.netloc}"
    return Settings(
        host=_env("HOST", default="127.0.0.1"),
        port=port,
        dev=_env("DEV", default="0") == "1",
        frontend_url=frontend_url,
        allowed_origins=tuple(o.strip().rstrip("/") for o in origins.split(",") if o.strip()),
        data_dir=Path(_env("DATA_DIR", default=str(REPO_ROOT / "data"))),
        web_dist=Path(_env("WEB_DIST", default=str(REPO_ROOT / "web" / "dist"))),
        user_agent=_env(
            "USER_AGENT",
            default="Sideways/0.1 (+https://github.com/owenzhang04/spotify-recommender)",
        ),
        spotify_client_id=_env("SPOTIFY_CLIENT_ID", "SPOTIPY_CLIENT_ID"),
        spotify_client_secret=_env("SPOTIFY_CLIENT_SECRET", "SPOTIPY_CLIENT_SECRET"),
        spotify_redirect_uri=redirect,
        typesafe_api_key=_env("TYPESAFE_API_KEY"),
        jev_model=_env("JEV_MODEL", default="jev-latest"),
    )


settings = load_settings()
