/** Everything that defines a result set lives in the URL, so any page is a shareable link. */

export type Params = {
  seeds: number[]
  liked: number[]
  skipped: number[]
  /** 0 = familiar, 100 = adventurous */
  adv: number
  steer: string
}

export const DEFAULT_ADV = 50
const MAX_IDS = 50

function ids(value: string | null): number[] {
  if (!value) return []
  const out: number[] = []
  for (const part of value.split(',')) {
    const n = Number(part)
    if (Number.isSafeInteger(n) && n > 0 && !out.includes(n)) out.push(n)
  }
  return out.slice(0, MAX_IDS)
}

export function parseParams(search: string): Params {
  const q = new URLSearchParams(search)
  const advRaw = Number(q.get('adv'))
  const adv = q.has('adv') && Number.isFinite(advRaw) ? Math.round(advRaw) : DEFAULT_ADV
  return {
    seeds: ids(q.get('s')).slice(0, 25),
    liked: ids(q.get('l')),
    skipped: ids(q.get('k')),
    adv: Math.min(100, Math.max(0, adv)),
    steer: (q.get('q') ?? '').slice(0, 200),
  }
}

export function serializeParams(p: Params): string {
  const q = new URLSearchParams()
  if (p.seeds.length) q.set('s', p.seeds.join(','))
  if (p.liked.length) q.set('l', p.liked.join(','))
  if (p.skipped.length) q.set('k', p.skipped.join(','))
  if (p.adv !== DEFAULT_ADV) q.set('adv', String(p.adv))
  if (p.steer) q.set('q', p.steer)
  const s = q.toString()
  return s ? `?${s}` : ''
}
