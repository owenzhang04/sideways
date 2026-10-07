export type Artist = { deezer_id: number; name: string; picture: string; fans: number }

export type Track = {
  id: number
  title: string
  preview: string
  album: string
  cover: string
  link: string
  duration: number
}

export type Rec = {
  deezer_id: number
  name: string
  picture: string
  fans: number | null
  tags: string[]
  shared_tags: string[]
  because: string[]
  via: string | null
  sources: string[]
  track: Track | null
  walk: number
  steer_match: number | null
}

export type Seed = { deezer_id: number; name: string; picture: string }

export type RecResult = { seeds: Seed[]; recs: Rec[]; warnings: string[]; steered: boolean }

export type SteerStatus = 'off' | 'loading' | 'ready' | 'failed'

export type Config = { spotify_login: boolean; steer: SteerStatus }

export type RecommendBody = {
  seeds: number[]
  liked: number[]
  skipped: number[]
  exclude_names: string[]
  adventurousness: number
  steer: string
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init)
  if (!resp.ok) {
    let message = `Request failed (${resp.status}).`
    try {
      const body = await resp.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // Non-JSON error body (proxy or network page); keep the generic message.
    }
    throw new ApiError(resp.status, message)
  }
  return resp.json() as Promise<T>
}

function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return call<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
}

export const api = {
  config: () => call<Config>('/api/config'),
  searchArtists: (q: string, signal?: AbortSignal) =>
    call<Artist[]>(`/api/artists/search?q=${encodeURIComponent(q)}`, { signal }),
  recommend: (body: RecommendBody, signal?: AbortSignal) =>
    post<RecResult>('/api/recommend', body, signal),
  freshPreview: (trackId: number) =>
    call<{ preview: string }>(`/api/tracks/${trackId}/preview`),
  spotifyMe: () => call<{ logged_in: boolean }>('/api/spotify/me'),
  spotifySeeds: () => call<{ seeds: Artist[]; known: string[] }>('/api/spotify/seeds'),
  savePlaylist: (name: string, tracks: { deezer_track_id: number; title: string; artist: string }[]) =>
    post<{ url: string; added: number; missing: string[] }>('/api/spotify/playlist', { name, tracks }),
  logout: () => post<{ ok: boolean }>('/api/spotify/logout', {}),
}
