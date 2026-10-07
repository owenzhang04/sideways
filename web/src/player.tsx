/** One shared <audio> element: starting a preview stops the previous one. */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api, type Track } from './api'
import { PlayerContext, type PlayerState } from './playerContext'

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audio = useRef<HTMLAudioElement | null>(null)
  const retried = useRef<Set<number>>(new Set())
  const [currentId, setCurrentId] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const [failedId, setFailedId] = useState<number | null>(null)

  useEffect(() => {
    const el = new Audio()
    el.preload = 'none'
    audio.current = el
    const onTime = () => setProgress(el.currentTime)
    const onEnd = () => {
      setPlaying(false)
      setProgress(0)
    }
    const onPause = () => setPlaying(false)
    const onPlay = () => setPlaying(true)
    const events = { timeupdate: onTime, ended: onEnd, pause: onPause, play: onPlay }
    for (const [name, fn] of Object.entries(events)) el.addEventListener(name, fn)
    return () => {
      el.pause()
      for (const [name, fn] of Object.entries(events)) el.removeEventListener(name, fn)
    }
  }, [])

  const value = useMemo<PlayerState>(() => {
    // Deezer preview URLs are signed and expire after ~20 minutes; fetch a fresh one once.
    async function play(el: HTMLAudioElement, track: Track, src: string) {
      el.src = src
      try {
        await el.play()
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        if (retried.current.has(track.id)) {
          setFailedId(track.id)
          return
        }
        retried.current.add(track.id)
        try {
          const { preview } = await api.freshPreview(track.id)
          await play(el, track, preview)
        } catch {
          setFailedId(track.id)
        }
      }
    }

    return {
      currentId,
      playing,
      progress,
      failedId,
      toggle(track: Track) {
        const el = audio.current
        if (!el || !track.preview) return
        if (currentId === track.id) {
          if (el.paused) void el.play()
          else el.pause()
          return
        }
        el.pause()
        setCurrentId(track.id)
        setProgress(0)
        setFailedId(null)
        void play(el, track, track.preview)
      },
    }
  }, [currentId, playing, progress, failedId])

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>
}
