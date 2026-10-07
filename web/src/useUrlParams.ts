import { useCallback, useEffect, useState } from 'react'
import { parseParams, serializeParams, type Params } from './urlState'

/**
 * URL-backed state. Seed changes push a history entry so Back returns to the previous list;
 * everything else replaces the current entry.
 */
export function useUrlParams(): [Params, (patch: Partial<Params>) => void] {
  const [params, setParams] = useState(() => parseParams(window.location.search))

  useEffect(() => {
    const onPop = () => setParams(parseParams(window.location.search))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const update = useCallback((patch: Partial<Params>) => {
    setParams((prev) => {
      const next = { ...prev, ...patch }
      const url = `${window.location.pathname}${serializeParams(next)}`
      const seedsChanged = patch.seeds !== undefined && patch.seeds.join() !== prev.seeds.join()
      if (seedsChanged) window.history.pushState(null, '', url)
      else window.history.replaceState(null, '', url)
      return next
    })
  }, [])

  return [params, update]
}
