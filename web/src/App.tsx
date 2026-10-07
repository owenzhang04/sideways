import { useCallback, useEffect, useEffectEvent, useState } from 'react'
import { api, ApiError, type Artist, type Config, type RecResult } from './api'
import { Colophon } from './components/Colophon'
import { Controls } from './components/Controls'
import { Landing } from './components/Landing'
import { Masthead } from './components/Masthead'
import { RecEntry } from './components/RecEntry'
import { headline, issueNumber, pad } from './copy'
import { PlayerProvider } from './player'
import { loadKnown, loadNames, rememberNames, saveKnown } from './storage'
import { useUrlParams } from './useUrlParams'

const LOADING_LINES = [
  'Reading ListenBrainz listening sessions…',
  'Asking Deezer for neighbors…',
  'Walking the graph…',
  'Pulling previews…',
]

const SPOTIFY_NOTICES: Record<string, string> = {
  connected: 'Connected to Spotify.',
  denied: 'Spotify login was cancelled.',
  expired: 'That Spotify login link expired. Try again.',
  failed: "Spotify didn't finish the login. If your account isn't on the approved list, it can't connect yet.",
}

export default function App() {
  const [params, update] = useUrlParams()
  const [config, setConfig] = useState<Config>({ spotify_login: false, steer: 'off' })
  const [spotifyConnected, setSpotifyConnected] = useState(false)
  const [names, setNames] = useState(loadNames)
  const [result, setResult] = useState<RecResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingLine, setLoadingLine] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(() => {
    const status = new URLSearchParams(window.location.search).get('spotify')
    return status ? (SPOTIFY_NOTICES[status] ?? '') : ''
  })
  const [tune, setTune] = useState(0)
  const [applied, setApplied] = useState({ liked: params.liked, skipped: params.skipped })
  const [spotifyBusy, setSpotifyBusy] = useState(false)
  const [saved, setSaved] = useState<{ url: string; added: number } | null>(null)

  const remember = useCallback((entries: { deezer_id: number; name: string; picture: string }[]) => {
    rememberNames(entries)
    setNames(loadNames())
  }, [])

  useEffect(() => {
    api.config().then(setConfig, () => undefined)
    const q = new URLSearchParams(window.location.search)
    if (q.has('spotify')) {
      q.delete('spotify')
      const rest = q.toString()
      window.history.replaceState(null, '', `${window.location.pathname}${rest ? `?${rest}` : ''}`)
    }
  }, [])

  // The steering model loads after the server starts; check back until it settles.
  useEffect(() => {
    if (config.steer !== 'loading') return
    const t = setInterval(() => api.config().then(setConfig, () => undefined), 5000)
    return () => clearInterval(t)
  }, [config.steer])

  useEffect(() => {
    if (config.spotify_login) api.spotifyMe().then((r) => setSpotifyConnected(r.logged_in), () => undefined)
  }, [config.spotify_login])

  // Reads the latest likes/skips without making them refetch triggers: those wait for Re-tune.
  const fetchRecs = useEffectEvent(async (signal: AbortSignal) => {
    setLoading(true)
    setLoadingLine(0)
    setError('')
    setSaved(null)
    try {
      const res = await api.recommend(
        {
          seeds: params.seeds,
          liked: params.liked,
          skipped: params.skipped,
          exclude_names: loadKnown(),
          adventurousness: params.adv / 100,
          steer: params.steer,
        },
        signal,
      )
      remember([...res.seeds, ...res.recs])
      setResult(res)
      setApplied({ liked: params.liked, skipped: params.skipped })
    } catch (err) {
      if (signal.aborted) return
      setError(err instanceof ApiError || err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      if (!signal.aborted) setLoading(false)
    }
  })

  const seedKey = params.seeds.join(',')
  useEffect(() => {
    if (!seedKey) return
    const ctrl = new AbortController()
    const timer = setTimeout(() => void fetchRecs(ctrl.signal), 250)
    return () => {
      clearTimeout(timer)
      ctrl.abort()
    }
  }, [seedKey, params.adv, params.steer, tune])

  useEffect(() => {
    if (!loading) return
    const t = setInterval(() => setLoadingLine((i) => Math.min(i + 1, LOADING_LINES.length - 1)), 2200)
    return () => clearInterval(t)
  }, [loading])

  const start = (artists: Artist[]) => {
    if (!artists.length) return
    remember(artists)
    update({ seeds: artists.map((a) => a.deezer_id), liked: [], skipped: [], steer: '' })
  }

  const startFromSpotify = async () => {
    setSpotifyBusy(true)
    setError('')
    try {
      const { seeds, known } = await api.spotifySeeds()
      saveKnown(known)
      if (!seeds.length) throw new Error("Couldn't match your Spotify artists to the catalog.")
      start(seeds)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Spotify did not respond.')
      if (err instanceof ApiError && err.status === 401) setSpotifyConnected(false)
    } finally {
      setSpotifyBusy(false)
    }
  }

  const goHome = () => {
    saveKnown([])
    update({ seeds: [], liked: [], skipped: [], steer: '' })
  }

  const issue = params.seeds.length ? issueNumber(params.seeds) : null
  const seedNames = params.seeds.map((id) => names[id]?.name).filter((n): n is string => Boolean(n))
  const pending =
    params.liked.filter((id) => !applied.liked.includes(id)).length +
    params.skipped.filter((id) => !applied.skipped.includes(id)).length +
    applied.liked.filter((id) => !params.liked.includes(id)).length +
    applied.skipped.filter((id) => !params.skipped.includes(id)).length

  const verdict = (id: number) =>
    params.liked.includes(id) ? 'liked' : params.skipped.includes(id) ? 'skipped' : null

  const setVerdict = (id: number, v: 'liked' | 'skipped' | null) => {
    const liked = params.liked.filter((x) => x !== id)
    const skipped = params.skipped.filter((x) => x !== id)
    if (v === 'liked') liked.push(id)
    if (v === 'skipped') skipped.push(id)
    update({ liked, skipped })
  }

  const shown = seedKey ? result : null
  const visibleRecs = shown?.recs ?? []

  const savePlaylist = async () => {
    const tracks = visibleRecs
      .filter((r) => r.track && !params.skipped.includes(r.deezer_id))
      .map((r) => ({ deezer_track_id: r.track!.id, title: r.track!.title, artist: r.name }))
    try {
      const name = `Sideways No. ${pad(issue ?? 0, 3)}: ${headline(seedNames).replace(/\.$/, '')}`.slice(0, 100)
      const res = await api.savePlaylist(name, tracks)
      setSaved(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Saving to Spotify failed.')
    }
  }

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setNotice('Link copied. Anyone with it sees this same list.')
    } catch {
      setNotice('Copy the address bar to share this list.')
    }
  }

  return (
    <PlayerProvider>
      <div className="page">
        <Masthead issue={issue} onHome={goHome} />
        {notice && (
          <p className="notice" role="status">
            {notice}{' '}
            <button type="button" className="textbtn" onClick={() => setNotice('')}>
              Dismiss
            </button>
          </p>
        )}

        {params.seeds.length === 0 ? (
          <Landing
            onStart={start}
            spotifyLogin={config.spotify_login}
            spotifyConnected={spotifyConnected}
            onUseSpotify={startFromSpotify}
            busy={spotifyBusy}
          />
        ) : (
          <div className="layout">
            <aside className="rail">
              <Controls
                seeds={params.seeds}
                liked={params.liked}
                names={names}
                adv={params.adv}
                steer={params.steer}
                steerStatus={config.steer}
                pending={pending}
                onAddSeed={(a) => {
                  remember([a])
                  update({ seeds: [...params.seeds, a.deezer_id] })
                }}
                onRemoveSeed={(id) => update({ seeds: params.seeds.filter((x) => x !== id) })}
                onAdv={(adv) => update({ adv })}
                onSteer={(steer) => update({ steer })}
                onRetune={() => setTune((t) => t + 1)}
              >
                <div className="controls__group controls__actions">
                  <button type="button" className="textbtn textbtn--strong" onClick={copyLink}>
                    Copy link to this list
                  </button>
                  {spotifyConnected && shown && (
                    <button type="button" className="textbtn textbtn--strong" onClick={savePlaylist}>
                      Save to Spotify playlist
                    </button>
                  )}
                  {saved && (
                    <a className="textbtn" href={saved.url} target="_blank" rel="noopener noreferrer">
                      Saved {saved.added} tracks. Open playlist ↗
                    </a>
                  )}
                </div>
              </Controls>
            </aside>

            <main className="feature" aria-busy={loading}>
              <header className="feature__head">
                <p className="kicker">This issue</p>
                <h2 className="feature__headline">{headline(seedNames) || 'Your list'}</h2>
                {loading && (
                  <p className="feature__status" role="status">
                    {LOADING_LINES[loadingLine]}
                  </p>
                )}
                {shown?.warnings.map((w) => (
                  <p key={w} className="notice notice--warn">
                    {w}
                  </p>
                ))}
                {error && <p className="notice notice--error">{error}</p>}
              </header>

              {!shown && loading && <SkeletonList />}
              {shown && (
                <ol className={`entries${loading ? ' entries--stale' : ''}`}>
                  {visibleRecs.map((rec, i) => (
                    <RecEntry
                      key={rec.deezer_id}
                      rec={rec}
                      index={i + 1}
                      verdict={verdict(rec.deezer_id)}
                      showSteer={shown.steered}
                      onLike={() => setVerdict(rec.deezer_id, 'liked')}
                      onSkip={() => setVerdict(rec.deezer_id, 'skipped')}
                      onUndo={() => setVerdict(rec.deezer_id, null)}
                    />
                  ))}
                </ol>
              )}
              {shown && shown.recs.length === 0 && !loading && (
                <p className="notice">Nothing new turned up. Try adding a different seed or wandering further.</p>
              )}
            </main>
          </div>
        )}
        <Colophon />
      </div>
    </PlayerProvider>
  )
}

function SkeletonList() {
  return (
    <ol className="entries" aria-hidden="true">
      {Array.from({ length: 5 }, (_, i) => (
        <li key={i} className="entry entry--ghost">
          <span className="entry__num">{pad(i + 1)}</span>
          <div className="entry__art">
            <div className="entry__art-blank" />
          </div>
          <div className="entry__body">
            <div className="ghost ghost--title" />
            <div className="ghost" />
            <div className="ghost ghost--short" />
          </div>
        </li>
      ))}
    </ol>
  )
}
