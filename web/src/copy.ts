/** Words: liner-note reasons, numbers, and the masthead. */

import type { Rec } from './api'

export function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? ''
  if (names.length === 2) return `${names[0]} and ${names[1]}`
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/** One liner-note sentence. Names only the two strongest seeds so entries read differently. */
export function reason(rec: Rec): string {
  const names = rec.because.slice(0, 2)
  const scene = rec.shared_tags[0]
  if (rec.via && names.length) return `One step past ${rec.via}, by way of ${names[0]}.`
  if (names.length === 0) return 'A longer walk from your seeds.'
  const lead = names.length === 1 ? `Sits right next to ${names[0]}` : `Where ${joinNames(names)} overlap`
  return scene ? `${lead}, on the ${scene} side.` : `${lead}.`
}

export function sourceLabel(sources: string[]): string {
  const labels = { listenbrainz: 'ListenBrainz', deezer: 'Deezer' } as Record<string, string>
  return sources.map((s) => labels[s] ?? s).join(' + ')
}

export function compactNumber(n: number): string {
  if (n >= 1_000_000) return `${trim(n / 1_000_000)}M`
  if (n >= 1_000) return `${trim(n / 1_000)}K`
  return String(n)
}

function trim(x: number): string {
  return x >= 100 ? Math.round(x).toString() : x.toFixed(1).replace(/\.0$/, '')
}

export function headline(names: string[]): string {
  if (names.length === 0) return ''
  if (names.length <= 3) return `For people who like ${joinNames(names)}.`
  const rest = names.length - 2
  return `For people who like ${names[0]}, ${names[1]} and ${rest} others.`
}

/** Same seeds, same issue number: a small stable hash of the sorted seed IDs, 1 to 999. */
export function issueNumber(seeds: number[]): number {
  let h = 7
  for (const id of [...seeds].sort((a, b) => a - b)) h = (h * 31 + id) % 1_000_003
  return (h % 999) + 1
}

export function pad(n: number, width = 2): string {
  return String(n).padStart(width, '0')
}

export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${pad(s % 60)}`
}
