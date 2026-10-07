"""Optional TypeSafe Jev re-rank.

Jev only scores. Candidates come from the graph (real catalog artists), and Jev answers
per-candidate questions about them, so it can't introduce an artist that doesn't exist.
One request per candidate keeps the state small, which Jev's docs say keeps accuracy up.
"""

import asyncio
import logging
from dataclasses import dataclass

from typesafe_sdk import AsyncTypeSafeClient, Noul, NoulCriteria, TypeSafeError

from sideways.engine.rank import JevScores
from sideways.http import RateLimiter

log = logging.getLogger(__name__)

FITS_TASTE = Noul(
    instructions=(
        "Would a listener who loves every artist in listener.loves enjoy the candidate artist?"
    ),
    criteria=NoulCriteria(
        true="The candidate's sound, scene or era clearly overlaps with what the listener loves",
        false="The candidate would likely feel out of place next to what the listener loves",
    ),
)
MATCHES_STEER = Noul(
    instructions="Does the candidate artist satisfy the listener's request in listener.request?",
    criteria=NoulCriteria(
        true="The candidate fits every part of the request",
        false="The candidate contradicts or misses part of the request",
    ),
)
# Stay under the key's 1,200 requests/minute limit.
REQUESTS_PER_SECOND = 15
CONCURRENCY = 12


@dataclass(frozen=True)
class Candidate:
    key: str
    name: str
    tags: list[str]
    similar_to: list[str]


class JevRanker:
    def __init__(self, client: AsyncTypeSafeClient, model: str) -> None:
        self.client = client
        self.model = model
        self.limiter = RateLimiter(REQUESTS_PER_SECOND)
        self.semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _score_one(self, listener: dict, steer: str, c: Candidate) -> JevScores | None:
        questions = {"fits_taste": FITS_TASTE}
        if steer:
            questions["matches_steer"] = MATCHES_STEER
        state = {
            "listener": listener | ({"request": steer} if steer else {}),
            "candidate": {"name": c.name, "tags": c.tags, "listeners_also_play": c.similar_to},
        }
        async with self.semaphore:
            await self.limiter.wait()
            try:
                resp = await self.client.system_one(
                    state=state, questions=questions, model=self.model
                )
            except TypeSafeError as e:
                log.warning("Jev failed for %s: %s", c.name, e)
                return None
        nouls = {name: answer.noul for name, answer in resp.nouls.items()}
        return JevScores(fits_taste=nouls["fits_taste"], matches_steer=nouls.get("matches_steer"))

    async def score(
        self, loves: list[str], loved_tags: list[str], steer: str, candidates: list[Candidate]
    ) -> dict[str, JevScores]:
        """Scores per candidate key. Candidates Jev failed on are left out (graph score stands)."""
        listener = {"loves": loves, "favorite_tags": loved_tags}
        results = await asyncio.gather(*(self._score_one(listener, steer, c) for c in candidates))
        return {c.key: r for c, r in zip(candidates, results, strict=True) if r is not None}
