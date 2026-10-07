import type { Rec } from '../api'
import { clock, compactNumber, pad, reason, sourceLabel } from '../copy'
import { usePlayer } from '../playerContext'

const PREVIEW_SECONDS = 30

type Props = {
  rec: Rec
  index: number
  verdict: 'liked' | 'skipped' | null
  showJev: boolean
  onLike: () => void
  onSkip: () => void
  onUndo: () => void
}

export function RecEntry({ rec, index, verdict, showJev, onLike, onSkip, onUndo }: Props) {
  const player = usePlayer()
  const track = rec.track
  const isCurrent = track !== null && player.currentId === track.id
  const isPlaying = isCurrent && player.playing
  const elapsed = isCurrent ? player.progress : 0
  const failed = track !== null && player.failedId === track.id

  if (verdict === 'skipped') {
    return (
      <li className="entry entry--skipped">
        <span className="entry__num">{pad(index)}</span>
        <span className="entry__skipped-name">{rec.name}</span>
        <span className="entry__skipped-note">set aside</span>
        <button type="button" className="textbtn" onClick={onUndo}>
          Undo
        </button>
      </li>
    )
  }

  return (
    <li className={`entry${verdict === 'liked' ? ' entry--liked' : ''}`}>
      <span className="entry__num" aria-hidden="true">
        {pad(index)}
      </span>

      <div className="entry__art">
        {track?.cover || rec.picture ? (
          <img src={track?.cover || rec.picture} alt="" loading="lazy" width={112} height={112} />
        ) : (
          <div className="entry__art-blank" />
        )}
        {track?.preview && (
          <button
            type="button"
            className={`play${isPlaying ? ' play--on' : ''}`}
            aria-label={`${isPlaying ? 'Pause' : 'Play'} preview of ${track.title} by ${rec.name}`}
            onClick={() => player.toggle(track)}
          >
            <span aria-hidden="true">{isPlaying ? '❚❚' : '▶'}</span>
          </button>
        )}
      </div>

      <div className="entry__body">
        <h3 className="entry__artist">{rec.name}</h3>
        {track && (
          <p className="entry__track">
            <span className="entry__title">“{track.title}”</span>
            {track.album && track.album !== track.title && <span className="entry__album"> from {track.album}</span>}
          </p>
        )}
        {track?.preview && (
          <div className="meter" aria-hidden="true">
            <div className="meter__bar" style={{ width: `${(elapsed / PREVIEW_SECONDS) * 100}%` }} />
            <span className="meter__time">
              {clock(elapsed)} / {clock(PREVIEW_SECONDS)}
            </span>
          </div>
        )}
        {failed && <p className="entry__warn">This preview won't load. Try the Deezer link.</p>}

        <p className="entry__reason">{reason(rec)}</p>

        <div className="entry__meta">
          {rec.tags.slice(0, 4).map((t) => (
            <span key={t} className={`tag${rec.shared_tags.includes(t) ? ' tag--shared' : ''}`}>
              {t}
            </span>
          ))}
          {rec.fans !== null && <span className="entry__fans">{compactNumber(rec.fans)} fans</span>}
          {rec.sources.length > 0 && (
            <span className="entry__fans" title="Which similarity sources link this artist to your seeds">
              via {sourceLabel(rec.sources)}
            </span>
          )}
          {showJev && rec.jev?.matches_steer != null && (
            <span className="entry__jev" title="Jev's probability that this artist matches your request">
              fits request {Math.round(rec.jev.matches_steer * 100)}%
            </span>
          )}
        </div>

        <div className="entry__actions">
          <button
            type="button"
            className={`chipbtn${verdict === 'liked' ? ' chipbtn--on' : ''}`}
            aria-pressed={verdict === 'liked'}
            onClick={verdict === 'liked' ? onUndo : onLike}
          >
            {verdict === 'liked' ? '✓ Kept' : '+ Keep'}
          </button>
          <button type="button" className="chipbtn" onClick={onSkip}>
            Not for me
          </button>
          {track?.link && (
            <a className="textbtn" href={track.link} target="_blank" rel="noopener noreferrer">
              Deezer ↗
            </a>
          )}
          <a
            className="textbtn"
            href={`https://open.spotify.com/search/${encodeURIComponent(`${rec.name} ${track?.title ?? ''}`.trim())}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Spotify ↗
          </a>
        </div>
      </div>
    </li>
  )
}
