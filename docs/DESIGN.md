# Sideways — Design

Music recommendations one step sideways from what you already like. A hosted
portfolio site: type in a few artists (or log in with Spotify for better seeds),
get one ranked list of artists you don't know yet, each with a 30-second preview
and a reason.

Rebuild of the v1 "Spotify Recommender" (2026-10-07). Research behind the
decisions: `docs/research/2026-10-07-rec-landscape.md`.

## Decisions

| Area | Choice | Why |
|---|---|---|
| Audience | Public, hosted | Portfolio piece. Spotify Dev Mode caps apps at 5 users, so Spotify can't be the only way in |
| Taste input | Typed seed artists (anyone) + optional Spotify login (allowlisted) | Typed seeds work for every visitor; Spotify adds weighted top artists + saved tracks |
| Similarity data | ListenBrainz session-based similar artists + Deezer related artists | Spotify removed related-artists, top-tracks, popularity for Dev Mode apps |
| Tags | ListenBrainz batch artist metadata (MusicBrainz folksonomy) | Spotify genres come back empty |
| Tracks / previews | Deezer artist top tracks (30s MP3 previews, cover art) | No auth, ~50 req / 5 s |
| Ranking | Personalized PageRank over the merged similarity graph, popularity penalty, MMR diversity | Same core idea as v1, but on a graph that actually reaches beyond your library |
| LLM | Optional TypeSafe Jev re-rank when `TYPESAFE_API_KEY` is set | Jev scores grounded candidates; it never names artists, so nothing is hallucinated |
| Stack | FastAPI (Python 3.14, uv) + React 19 / Vite / TypeScript | Python for networkx; TS for the interactive player UI |
| State | Stateless API; seeds, likes, skips, slider live in the URL (+ localStorage) | Shareable links for free; no user DB |
| Cache | SQLite key-value with TTL for every upstream response | Upstreams are slow (MusicBrainz 1 req/s) and free; be polite |

## Pipeline

```
seeds (typed Deezer IDs, or Spotify-derived, weighted)
  ├─ resolve: Deezer artist (name, fans, image) + MBID via MusicBrainz search (cached)
  ├─ edges:  ListenBrainz similar-artists(mbid)   score-normalized per seed
  │          Deezer /artist/{id}/related           rank-decayed weights
  │          merged by MBID, else normalized name; agreement across sources boosts weight
  ├─ graph:  seed → neighbor edges (1 hop) + neighbor → neighbor edges among top candidates (2nd hop)
  ├─ PPR:    personalization = seed weights (+ liked recs); skipped recs run a negative PPR, subtracted
  ├─ score:  log(ppr) − adventurousness · β · log10(fans)   ; known artists removed
  ├─ tags:   ListenBrainz batch metadata for top candidates
  ├─ Jev:    (optional) per candidate: fits_taste, matches_steer → blended into score
  ├─ MMR:    diversity re-rank on tag Jaccard (λ = 0.75)
  └─ track:  Deezer top track per artist (preview, cover, ISRC)
reason: top contributing seeds ("Alvvays and Slowdive point here") + shared tags
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | Feature flags: `spotify_login`, `jev` |
| GET | `/api/artists/search?q=` | Seed autocomplete (Deezer) |
| POST | `/api/recommend` | `{seeds, liked, skipped, adventurousness, steer?, limit}` → ranked recs |
| GET | `/api/spotify/login` · `/api/spotify/callback` | OAuth (PKCE), session cookie |
| GET | `/api/spotify/seeds` | Logged-in user's weighted seed artists, mapped to Deezer |
| POST | `/api/spotify/playlist` | Save recs to a new private playlist (`POST /me/playlists`, `/playlists/{id}/items`) |
| POST | `/api/spotify/logout` | Clear session |

## Visual design — "record-store editorial"

- Warm paper background, ink text, one vermilion accent. Dark mode = ink paper, warm off-white text.
- Display serif (Instrument Serif) for headlines and artist names; Newsreader for body; JetBrains Mono for numbers, ranks, timestamps.
- Masthead with "issue no." derived from the seed set (same seeds → same issue number).
- Each rec is a numbered entry: cover art, artist (big serif), track title in quotes, play button with 30s progress, liner-notes reason, tags, like/skip.
- Controls in a slim rail: seed chips with add-box, familiar↔adventurous slider, steer box (only if Jev on), save-to-Spotify, copy link.
- Mobile-first single column; two-column (controls rail + list) at ≥960px.

## Out of scope (v1 of the rebuild)

Accounts beyond Spotify session, audio-content embeddings (CLAP/MERT), LLM-written blurbs,
listening-session/radio mode, graph explorer view.

## Evaluation

`api/scripts/eval_holdout.py`: for a seed set, hold out one seed at a time, recommend from
the rest, record recall@20 of held-out seed (and its LB top-5 neighbors). Run graph-only vs
graph+Jev once a key is available.

## Evaluation results (2026-10-07)

Leave-one-out result on 2026-10-07 (8 seed sets x 4 artists, top 20, slider at 0.5):

| Similarity source | Held-out artist recovered | Mean rank when recovered |
|---|---|---|
| Deezer only | 20/32 (62%) | 6.8 |
| ListenBrainz only | 22/32 (69%) | 3.8 |
| Both, merged | 26/32 (81%) | 5.2 |

32 trials is a small sample, and recall only shows the graph finds artists you already like,
not that its new picks are good. Jev has not been evaluated (no API key yet).

## Known risks

- ListenBrainz similar-artists is a "labs" endpoint; no SLA. Deezer-only fallback keeps the app working.
- Deezer public API terms: preview use for non-commercial apps; no auth, rate-limited.
- MusicBrainz name search can mismatch homonyms; mitigated by preferring candidates whose
  LB/Deezer neighbors overlap.
