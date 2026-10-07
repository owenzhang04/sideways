"""Pre-fetch the landing page's example seed sets so first-time visitors get cached speed.

Run after deploying (cache entries last 14 days for similarity, 10 minutes for previews,
so previews are re-fetched on first view either way).
"""

import asyncio
import time

from sideways.config import settings
from sideways.engine.pipeline import RecRequest
from sideways.main import build_services

# Keep in sync with EXAMPLES in web/src/components/Landing.tsx.
EXAMPLES = [
    ["Alvvays", "Slowdive", "Beach House"],
    ["Kendrick Lamar", "Little Simz", "Earl Sweatshirt"],
    ["Bill Evans", "Alice Coltrane", "Pharoah Sanders"],
    ["Charli xcx", "SOPHIE", "Caroline Polachek"],
]


async def main() -> None:
    async with build_services(settings) as svc:
        for names in EXAMPLES:
            start = time.time()
            found = [await svc.deezer.find_artist(n) for n in names]
            ids = [a.id for a in found if a]
            result = await svc.recommender.recommend(RecRequest(seeds=ids))
            took = time.time() - start
            print(f"{' / '.join(names)}: {len(result.recs)} recs in {took:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
