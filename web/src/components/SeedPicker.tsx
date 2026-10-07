import { useEffect, useId, useRef, useState } from 'react'
import { api, type Artist } from '../api'
import { compactNumber } from '../copy'

type Props = {
  onPick: (artist: Artist) => void
  exclude: number[]
  placeholder: string
  size?: 'large' | 'small'
  autoFocus?: boolean
}

export function SeedPicker({ onPick, exclude, placeholder, size = 'small', autoFocus }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Artist[]>([])
  const [active, setActive] = useState(0)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const listId = useId()
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const q = query.trim()
    if (!q) return
    const ctrl = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const found = await api.searchArtists(q, ctrl.signal)
        setResults(found.filter((a) => !exclude.includes(a.deezer_id)))
        setActive(0)
        setOpen(true)
        setError('')
      } catch (err) {
        if (!ctrl.signal.aborted) setError(err instanceof Error ? err.message : 'Search failed.')
      }
    }, 200)
    return () => {
      clearTimeout(timer)
      ctrl.abort()
    }
  }, [query, exclude])

  const visible = query.trim() ? results : []

  function pick(artist: Artist) {
    onPick(artist)
    setQuery('')
    setResults([])
    setOpen(false)
    input.current?.focus()
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, visible.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && open && visible[active]) {
      e.preventDefault()
      pick(visible[active])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const showList = open && visible.length > 0
  return (
    <div className={`picker picker--${size}`}>
      <input
        ref={input}
        className="picker__input"
        type="text"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-activedescendant={showList ? `${listId}-${active}` : undefined}
        aria-label="Add an artist"
        placeholder={placeholder}
        value={query}
        autoFocus={autoFocus}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={onKeyDown}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {error && <p className="picker__error">{error}</p>}
      {showList && (
        <ul className="picker__list" role="listbox" id={listId}>
          {visible.map((a, i) => (
            <li
              key={a.deezer_id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className="picker__option"
              onMouseDown={(e) => {
                e.preventDefault()
                pick(a)
              }}
              onMouseEnter={() => setActive(i)}
            >
              {a.picture ? <img src={a.picture} alt="" /> : <span className="picker__noimg" />}
              <span className="picker__name">{a.name}</span>
              <span className="picker__fans">{compactNumber(a.fans)} fans</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
