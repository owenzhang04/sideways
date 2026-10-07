import { createContext, useContext } from 'react'
import type { Track } from './api'

export type PlayerState = {
  currentId: number | null
  playing: boolean
  progress: number
  failedId: number | null
  toggle: (track: Track) => void
}

export const PlayerContext = createContext<PlayerState | null>(null)

export function usePlayer(): PlayerState {
  const ctx = useContext(PlayerContext)
  if (!ctx) throw new Error('usePlayer must be used inside <PlayerProvider>')
  return ctx
}
