"""Optional "steer it" re-ranking with GLiClass, a local zero-shot classifier (Knowledgator).

The listener's request ("upbeat, 90s") is split into labels, and the model scores how well
each candidate's description (name + genre tags) fits each label. GLiClass only scores
candidates the graph already found, so it can't introduce artists. It knows little about
individual artists; most of its signal comes from the tags.

Chosen by a side-by-side test on 2026-10-07: gliclass-base-v3.0 ranked the right artist
first for "upbeat dance music", "acoustic folk", "loud guitars" and "calm instrumental";
edge-v3.0, small-v1.0 and modern-base-v3.0 did not, and int8 quantization flattened all
scores to ~0.7.
"""

import asyncio
import logging
import re
import threading
import warnings
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

MAX_LABELS = 4
_SPLIT = re.compile(r"\s*(?:,|;|/|\band\b)\s*", re.IGNORECASE)


@dataclass(frozen=True)
class SteerCandidate:
    key: str
    name: str
    tags: list[str]


def split_request(request: str) -> list[str]:
    """'More upbeat, 90s and female vocals' -> ['more upbeat', '90s', 'female vocals']."""
    parts = [p.strip().lower() for p in _SPLIT.split(request) if p.strip()]
    return list(dict.fromkeys(parts))[:MAX_LABELS]


def describe(c: SteerCandidate) -> str:
    genres = ", ".join(c.tags) if c.tags else "unknown"
    return f"{c.name}. Genres: {genres}."


class SteerScorer(Protocol):
    @property
    def status(self) -> str:
        """'ready', 'loading' or 'failed'."""
        ...

    async def score(self, request: str, candidates: list[SteerCandidate]) -> dict[str, float]:
        """Per candidate key: mean label probability in [0, 1]."""
        ...


class GLiClassScorer:
    """Loads the model in a background thread so the API serves recs while it warms up."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._pipeline = None
        self._status = "loading"
        self._lock = threading.Lock()

    @property
    def status(self) -> str:
        return self._status

    def start_loading(self) -> None:
        threading.Thread(target=self._load, name="gliclass-load", daemon=True).start()

    def _load(self) -> None:
        try:
            with warnings.catch_warnings():
                # torch.jit warns on import under Python 3.14; gliclass doesn't use TorchScript.
                warnings.simplefilter("ignore", FutureWarning)
                from gliclass import GLiClassModel, ZeroShotClassificationPipeline
                from transformers import AutoTokenizer

            model = GLiClassModel.from_pretrained(self.model_name)
            tokenizer = AutoTokenizer.from_pretrained(self.model_name, add_prefix_space=True)
            self._pipeline = ZeroShotClassificationPipeline(
                model, tokenizer, classification_type="multi-label", device="cpu"
            )
            self._status = "ready"
            log.info("GLiClass model %s loaded", self.model_name)
        except Exception:
            self._status = "failed"
            log.exception("Could not load GLiClass model %s; steering disabled", self.model_name)

    def _score_sync(self, labels: list[str], texts: list[str]) -> list[float]:
        with self._lock:  # The pipeline isn't documented as thread-safe.
            results = self._pipeline(texts, labels, threshold=0.0)
        return [sum(r["score"] for r in row) / len(labels) if row else 0.0 for row in results]

    async def score(self, request: str, candidates: list[SteerCandidate]) -> dict[str, float]:
        labels = split_request(request)
        if self._status != "ready" or not labels or not candidates:
            return {}
        texts = [describe(c) for c in candidates]
        scores = await asyncio.to_thread(self._score_sync, labels, texts)
        return {c.key: s for c, s in zip(candidates, scores, strict=True)}
