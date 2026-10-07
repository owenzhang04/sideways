import { useState } from 'react'
import { api, type Artist } from '../api'
import { SeedPicker } from './SeedPicker'

const EXAMPLES = [
  ['Alvvays', 'Slowdive', 'Beach House'],
  ['Kendrick Lamar', 'Little Simz', 'Earl Sweatshirt'],
  ['Bill Evans', 'Alice Coltrane', 'Pharoah Sanders'],
  ['Charli xcx', 'SOPHIE', 'Caroline Polachek'],
]

type Props = {
  onStart: (artists: Artist[]) => void
  spotifyLogin: boolean
  spotifyConnected: boolean
  onUseSpotify: () => void
  busy: boolean
}

async function resolveExample(names: string[]): Promise<Artist[]> {
  const found = await Promise.all(
    names.map(async (name) => {
      const results = await api.searchArtists(name)
      const exact = results.filter((a) => a.name.toLowerCase() === name.toLowerCase())
      return (exact.length ? exact : results).sort((a, b) => b.fans - a.fans)[0]
    }),
  )
  return found.filter((a): a is Artist => Boolean(a))
}

export function Landing({ onStart, spotifyLogin, spotifyConnected, onUseSpotify, busy }: Props) {
  const [picked, setPicked] = useState<Artist[]>([])
  const [error, setError] = useState('')

  async function tryExample(names: string[]) {
    setError('')
    try {
      onStart(await resolveExample(names))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load that example.')
    }
  }

  return (
    <section className="landing">
      <h2 className="landing__ask">Name a few artists you can't stop playing.</h2>
      <p className="landing__sub">
        Three is a good start. Sideways looks at what their listeners also play, skips what you
        already know, and hands you a short list with a 30-second preview of each.
      </p>

      <SeedPicker
        size="large"
        autoFocus
        placeholder="Start typing an artist…"
        exclude={picked.map((a) => a.deezer_id)}
        onPick={(a) => setPicked((p) => [...p, a])}
      />

      {picked.length > 0 && (
        <div className="landing__picked">
          <ul className="chips">
            {picked.map((a) => (
              <li key={a.deezer_id} className="chip">
                {a.name}
                <button
                  type="button"
                  aria-label={`Remove ${a.name}`}
                  onClick={() => setPicked((p) => p.filter((x) => x.deezer_id !== a.deezer_id))}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="bigbtn" onClick={() => onStart(picked)}>
            Find music sideways →
          </button>
        </div>
      )}

      <div className="landing__examples">
        <span className="kicker">Or try</span>
        {EXAMPLES.map((names) => (
          <button key={names[0]} type="button" className="example" onClick={() => tryExample(names)}>
            {names.join(' · ')}
          </button>
        ))}
      </div>

      {spotifyLogin && (
        <div className="landing__spotify">
          {spotifyConnected ? (
            <button type="button" className="textbtn textbtn--strong" onClick={onUseSpotify} disabled={busy}>
              {busy ? 'Reading your Spotify listening…' : 'Start from my Spotify listening →'}
            </button>
          ) : (
            <a className="textbtn textbtn--strong" href="/api/spotify/login">
              Or start from your Spotify listening →
            </a>
          )}
          <p className="fineprint">
            Spotify keeps apps like this to a short list of approved accounts, so login only
            works for people the site owner has added. Typing artists works for everyone.
          </p>
        </div>
      )}
      {error && <p className="notice notice--error">{error}</p>}
    </section>
  )
}
