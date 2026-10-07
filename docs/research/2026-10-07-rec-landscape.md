---
tags: [spotify-rec, recommender, music-apis, research]
date: 2026-10-07
sources_used:
  - https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide
  - https://developer.spotify.com/blog/2024-11-27-changes-to-the-web-api
  - https://techcrunch.com/2026/02/06/spotify-changes-developer-mode-api-to-require-premium-accounts-limits-test-users/
  - https://labs.api.listenbrainz.org/similar-artists
  - https://developers.deezer.com/api
  - https://musicbrainz.org/doc/MusicBrainz_API
  - https://www.last.fm/api/show/artist.getSimilar
  - https://arxiv.org/abs/2607.23718
  - https://arxiv.org/abs/2603.17540
  - https://arxiv.org/abs/2507.22224
confidence: high (API status, verified by live calls); medium (research trends)
---

# Music recommendation landscape for spotify-rec (Oct 2026)

## Bottom line
Live mode of v1 cannot work as written. Every external-discovery call it relies on
is gone for Development Mode apps, and "add yourself in User Management" does not
fix it. The rebuild should treat Spotify as a *taste source only* and get
similarity, candidates, tags and audio previews from open sources.

## What Spotify still allows (Dev Mode, after 2026-03-09)
Source: official February 2026 migration guide.

| Need | v1 used | Status |
|---|---|---|
| Related artists | `artist_related_artists` | Removed for new apps 2024-11-27 |
| Recommendations / audio features / previews | (not used) | Removed 2024-11-27 |
| Artist top tracks | `artist_top_tracks` | Removed 2026-03-09 |
| Batch `GET /artists`, `/tracks` | indirect | Removed 2026-03-09 |
| Artist `popularity`, `followers`; track `popularity` | ranking tiebreaks | Fields removed |
| Artist `genres` | genre histogram | Returned empty in practice (v1's "dev_mode_limited" detector) |
| Search | candidate pool | Max `limit` 10 (was 50) |
| Playlist contents | co-occurrence graph | Only playlists the user owns/collaborates on; `tracks` renamed `items` |
| `/me/top`, `/me/tracks`, recently played, playlist create | taste input | Still available |

Account limits: app owner needs **Premium**; new apps capped at **5 users**.

## Open sources (verified 2026-10-07 by live calls)

| Source | Auth | Verified response | Use |
|---|---|---|---|
| ListenBrainz labs `similar-artists/json` (session-based algo) | none | 100 neighbors w/ `artist_mbid`, `name`, `score` (Alvvays → Beach House 1863, Japanese Breakfast 1427) | Collaborative-filtering artist edges |
| Deezer `/artist/{id}/related` | none, ~50 req/5s | 20 related w/ `nb_fan` | Second edge source, popularity proxy |
| Deezer `/artist/{id}/top` | none | tracks w/ 30s `preview` MP3, `rank` | Track pick + in-page audio preview |
| MusicBrainz `/ws/2/artist?query=` | none, 1 req/s, UA required | `id`, folksonomy `tags` (Alvvays: shoegaze, indie pop, …) | Replace Spotify genres; ID bridge |
| Last.fm `artist.getSimilar`, `artist.getTopTags`, `user.getTopArtists` | free API key | unverified (no key set) | Third edge source; alt taste source via username, no OAuth |

## Assessment of v1 strategy
- **Genre histogram**: sound idea, dead data source. Re-base on MusicBrainz/Last.fm tags.
- **Co-occurrence PageRank over the user's own playlists**: the graph only contains
  artists the user already knows, so new artists enter only via related-artist
  bridges, which are now gone. Fix: build the graph from external CF similarity
  (ListenBrainz + Deezer, optionally Last.fm) and run Personalized PageRank seeded
  by the user's weighted artists. Agreement across sources is a strong signal.
- **Data volume**: 20 liked songs is thin. Pull more pages (saved tracks paginate fine).
- **Two parallel lists**: exposes algorithm internals to the user. Better: one ranked
  list with per-item reasons ("3 of your top artists point here"), plus a
  familiar ↔ adventurous control (popularity penalty via Deezer `nb_fan`).
- **Evaluation**: holdout script exists but only runs on stub data. Re-run leave-artists-out
  recall@k on a real profile once the new graph exists.
- **No feedback loop**: add like/skip on recs, persisted, fed back as positive/negative seeds.

## Where the field is (2025–2026)
- **Generative retrieval with semantic IDs** is the main industry direction
  (Spotify deployed it for podcast discovery, arXiv 2603.17540; practitioner
  handbook arXiv 2507.22224). Needs a large interaction corpus. Not applicable to a
  single-user app.
- **LLM agents over retrieval tools** (NetEase Cloud Music "Melo", arXiv 2607.23718):
  +2 pp playlist retention in A/B. Key lesson: ground every LLM-named entity against
  the catalog before showing it; on tool failure, retry with revised constraints rather
  than falling back to popular items. Applicable here at small scale: an optional
  natural-language "steer" box whose output is constraints on the graph ranking, not
  free-form song names.
- **Audio content embeddings** (CLAP, MERT) could replace removed audio features by
  embedding Deezer 30s previews locally. Real cost: model download (~hundreds of MB),
  CPU/GPU time per preview. Worth it only if "sounds like" matters more than "fans overlap".

## Recommended v2 pipeline
1. Taste: Spotify top artists (3 ranges) + saved tracks (paginated) + owned playlists → weighted seed artists.
2. Resolve seeds to MBIDs (MusicBrainz) and Deezer IDs (search), cached on disk.
3. Edges: ListenBrainz similar (score-normalized) + Deezer related (+ Last.fm if key).
4. Personalized PageRank from seeds; drop known artists; penalize by popularity per the adventurousness slider; diversity re-rank (MMR on tags).
5. Track per artist: Deezer top track with preview; link out via Spotify search URL or ISRC lookup.
6. Reasons: list which seeds contributed most mass + shared tags.
