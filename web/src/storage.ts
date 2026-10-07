/**
 * Per-browser conveniences. URLs carry only IDs, so artist names are remembered here to
 * label chips before the API answers. Storage can be unavailable (private mode), so every
 * access is guarded and the app works without it.
 */

export type Named = { name: string; picture: string }

const NAMES_KEY = 'sideways.names'
const KNOWN_KEY = 'sideways.known'
const MAX_NAMES = 500

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Quota or disabled storage: names fall back to the API response.
  }
}

export function loadNames(): Record<number, Named> {
  return read<Record<number, Named>>(NAMES_KEY, {})
}

export function rememberNames(entries: { deezer_id: number; name: string; picture: string }[]): void {
  const names = loadNames()
  for (const e of entries) names[e.deezer_id] = { name: e.name, picture: e.picture }
  const ids = Object.keys(names)
  const trimmed = ids.length > MAX_NAMES ? Object.fromEntries(ids.slice(-MAX_NAMES).map((k) => [k, names[Number(k)]])) : names
  write(NAMES_KEY, trimmed)
}

/** Artists from the user's Spotify library, excluded from recs. Never put in shared URLs. */
export function loadKnown(): string[] {
  return read<string[]>(KNOWN_KEY, [])
}

export function saveKnown(names: string[]): void {
  write(KNOWN_KEY, names)
}
