import { useState } from 'react'
import type { Artist } from '../api'
import type { Named } from '../storage'
import { SeedPicker } from './SeedPicker'

type Props = {
  seeds: number[]
  liked: number[]
  names: Record<number, Named>
  adv: number
  steer: string
  jev: boolean
  pending: number
  onAddSeed: (a: Artist) => void
  onRemoveSeed: (id: number) => void
  onAdv: (v: number) => void
  onSteer: (v: string) => void
  onRetune: () => void
  children?: React.ReactNode
}

export function Controls(props: Props) {
  const { seeds, liked, names, adv, steer, jev, pending } = props
  const [advDraft, setAdvDraft] = useState(adv)
  const [steerDraft, setSteerDraft] = useState(steer)
  const [synced, setSynced] = useState({ adv, steer })
  // Back/forward or a shared link can change these underneath the drafts.
  if (synced.adv !== adv || synced.steer !== steer) {
    setSynced({ adv, steer })
    setAdvDraft(adv)
    setSteerDraft(steer)
  }

  const label = (id: number) => names[id]?.name ?? '…'
  return (
    <div className="controls">
      <section className="controls__group">
        <h4 className="kicker">Your seeds</h4>
        <ul className="chips">
          {seeds.map((id) => (
            <li key={id} className="chip">
              {label(id)}
              {seeds.length > 1 && (
                <button type="button" aria-label={`Remove ${label(id)}`} onClick={() => props.onRemoveSeed(id)}>
                  ×
                </button>
              )}
            </li>
          ))}
        </ul>
        <SeedPicker placeholder="Add another artist" exclude={seeds} onPick={props.onAddSeed} />
      </section>

      {liked.length > 0 && (
        <section className="controls__group">
          <h4 className="kicker">Kept</h4>
          <p className="controls__kept">{liked.map(label).join(' · ')}</p>
        </section>
      )}

      <section className="controls__group">
        <label className="kicker" htmlFor="adv">
          How far to wander
        </label>
        <input
          id="adv"
          className="slider"
          type="range"
          min={0}
          max={100}
          step={5}
          value={advDraft}
          onChange={(e) => setAdvDraft(Number(e.target.value))}
          onPointerUp={() => props.onAdv(advDraft)}
          onKeyUp={() => props.onAdv(advDraft)}
          aria-valuetext={advDraft < 35 ? 'familiar' : advDraft > 65 ? 'adventurous' : 'balanced'}
        />
        <div className="slider__ends">
          <span>Familiar</span>
          <span>Adventurous</span>
        </div>
      </section>

      {jev && (
        <form
          className="controls__group"
          onSubmit={(e) => {
            e.preventDefault()
            props.onSteer(steerDraft.trim())
          }}
        >
          <label className="kicker" htmlFor="steer">
            Steer it
          </label>
          <input
            id="steer"
            className="field"
            type="text"
            maxLength={200}
            placeholder="e.g. more upbeat, women-fronted, 90s"
            value={steerDraft}
            onChange={(e) => setSteerDraft(e.target.value)}
          />
          <p className="fineprint">Jev scores each pick against your words; it can't invent artists.</p>
        </form>
      )}

      {pending > 0 && (
        <button type="button" className="bigbtn bigbtn--small" onClick={props.onRetune}>
          Re-tune with {pending} {pending === 1 ? 'change' : 'changes'}
        </button>
      )}

      {props.children}
    </div>
  )
}
