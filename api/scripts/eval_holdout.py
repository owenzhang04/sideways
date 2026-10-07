"""Leave-one-out recall: hide one seed, recommend from the rest, see if it comes back.

Compares similarity sources (Deezer only, ListenBrainz only, both) on real data. A hit means
the held-out artist appears in the top-k recommendations. This measures whether the graph
recovers an artist the listener demonstrably likes; it says nothing about novelty.

Usage: uv run python scripts/eval_holdout.py [--k 20]
Results are cached in data/cache.db, so a second run takes seconds.
"""

import argparse
import asyncio
import statistics
from dataclasses import replace

from sideways.config import settings
from sideways.engine.pipeline import Recommender, RecRequest
from sideways.main import build_services
from sideways.names import norm_name

SEED_SETS = [
    ["Alvvays", "Slowdive", "Beach House", "Wild Nothing"],
    ["Kendrick Lamar", "Little Simz", "Earl Sweatshirt", "JPEGMAFIA"],
    ["Bill Evans", "Alice Coltrane", "Pharoah Sanders", "John Coltrane"],
    ["Charli xcx", "SOPHIE", "Caroline Polachek", "A. G. Cook"],
    ["Mitski", "Big Thief", "Phoebe Bridgers", "Adrianne Lenker"],
    ["Radiohead", "Portishead", "Massive Attack", "Björk"],
    ["Aphex Twin", "Boards of Canada", "Burial", "Four Tet"],
    ["Fleetwood Mac", "Steely Dan", "Joni Mitchell", "Carole King"],
]


class _NoSimilar:
    async def similar_artists(self, mbid: str, limit: int = 50) -> list:
        return []

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    def __init__(self, inner) -> None:
        self.inner = inner


class _NoRelated:
    async def related(self, artist_id: int) -> list:
        return []

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    def __init__(self, inner) -> None:
        self.inner = inner


async def trial(rec: Recommender, ids: dict[str, int], held: str, k: int) -> int | None:
    seeds = [i for name, i in ids.items() if name != held]
    result = await rec.recommend(RecRequest(seeds=seeds, limit=k))
    names = [norm_name(r.name) for r in result.recs]
    return names.index(norm_name(held)) + 1 if norm_name(held) in names else None


async def main(k: int) -> None:
    async with build_services(replace(settings, steer_model="")) as svc:
        base = svc.recommender
        variants = {
            "deezer only": Recommender(base.deezer, _NoSimilar(base.lb), base.mb),
            "listenbrainz only": Recommender(_NoRelated(base.deezer), base.lb, base.mb),
            "both": base,
        }
        sets = []
        for names in SEED_SETS:
            found = {n: await svc.deezer.find_artist(n) for n in names}
            sets.append({n: a.id for n, a in found.items() if a})

        print(f"Leave-one-out recall@{k} over {sum(len(s) for s in sets)} held-out artists\n")
        for label, rec in variants.items():
            ranks = []
            for ids in sets:
                for held in ids:
                    ranks.append(await trial(rec, ids, held, k))
            hits = [r for r in ranks if r is not None]
            mean_rank = f"{statistics.mean(hits):.1f}" if hits else "-"
            print(
                f"{label:18} recall@{k} = {len(hits)}/{len(ranks)} ({len(hits) / len(ranks):.0%})"
                f"   mean rank of hits = {mean_rank}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=20)
    asyncio.run(main(parser.parse_args().k))
