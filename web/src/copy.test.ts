import { describe, expect, it } from 'vitest'
import type { Rec } from './api'
import { clock, compactNumber, headline, issueNumber, joinNames, reason, sourceLabel } from './copy'
import { DEFAULT_ADV, parseParams, serializeParams } from './urlState'

const rec = (over: Partial<Rec>): Rec => ({
  deezer_id: 1,
  name: 'X',
  picture: '',
  fans: 1,
  tags: [],
  shared_tags: [],
  because: [],
  via: null,
  sources: [],
  track: null,
  walk: 0,
  steer_match: null,
  ...over,
})

describe('copy', () => {
  it('joins names like a person would', () => {
    expect(joinNames([])).toBe('')
    expect(joinNames(['A'])).toBe('A')
    expect(joinNames(['A', 'B'])).toBe('A and B')
    expect(joinNames(['A', 'B', 'C'])).toBe('A, B and C')
  })

  it('writes reasons for direct, two-hop, and orphan recs', () => {
    expect(reason(rec({ because: ['Alvvays'] }))).toBe('Sits right next to Alvvays.')
    expect(reason(rec({ because: ['A', 'B', 'C'], shared_tags: ['shoegaze'] }))).toBe(
      'Where A and B overlap, on the shoegaze side.',
    )
    expect(reason(rec({ because: ['A'], via: 'M' }))).toBe('One step past M, by way of A.')
    expect(reason(rec({}))).toBe('A longer walk from your seeds.')
    expect(sourceLabel(['deezer', 'listenbrainz'])).toBe('Deezer + ListenBrainz')
    expect(sourceLabel([])).toBe('')
  })

  it('formats numbers', () => {
    expect(compactNumber(950)).toBe('950')
    expect(compactNumber(37_403)).toBe('37.4K')
    expect(compactNumber(1_000)).toBe('1K')
    expect(compactNumber(4_101_126)).toBe('4.1M')
    expect(compactNumber(250_000)).toBe('250K')
    expect(clock(0)).toBe('0:00')
    expect(clock(29.7)).toBe('0:29')
    expect(clock(-3)).toBe('0:00')
  })

  it('writes a headline that stays short', () => {
    expect(headline([])).toBe('')
    expect(headline(['A', 'B', 'C'])).toBe('For people who like A, B and C.')
    expect(headline(['A', 'B', 'C', 'D', 'E'])).toBe('For people who like A, B and 3 others.')
  })

  it('gives the same issue number for the same seed set in any order', () => {
    expect(issueNumber([3, 1, 2])).toBe(issueNumber([1, 2, 3]))
    expect(issueNumber([1, 2, 3])).not.toBe(issueNumber([1, 2, 4]))
    for (const seeds of [[], [1], [987654321, 2]]) {
      const n = issueNumber(seeds)
      expect(n).toBeGreaterThanOrEqual(1)
      expect(n).toBeLessThanOrEqual(999)
    }
  })
})

describe('url state', () => {
  it('round-trips and omits defaults', () => {
    const p = { seeds: [5, 9], liked: [3], skipped: [], adv: 80, steer: 'more upbeat' }
    expect(parseParams(serializeParams(p))).toEqual(p)
    expect(serializeParams({ seeds: [], liked: [], skipped: [], adv: DEFAULT_ADV, steer: '' })).toBe('')
  })

  it('rejects junk from hand-edited links', () => {
    const p = parseParams('?s=1,abc,-4,1,2.5,7&adv=900&k=&q=' + 'x'.repeat(300))
    expect(p.seeds).toEqual([1, 7])
    expect(p.adv).toBe(100)
    expect(p.skipped).toEqual([])
    expect(p.steer).toHaveLength(200)
    expect(parseParams('?adv=nope').adv).toBe(DEFAULT_ADV)
    expect(parseParams('?s=' + Array.from({ length: 40 }, (_, i) => i + 1).join(',')).seeds).toHaveLength(25)
  })
})
