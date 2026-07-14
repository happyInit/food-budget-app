import { useEffect, useState } from 'react'

// 반응형 분기용 (예: 모바일 여부)
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(query).matches,
  )
  useEffect(() => {
    const m = window.matchMedia(query)
    const onChange = () => setMatches(m.matches)
    onChange()
    m.addEventListener('change', onChange)
    return () => m.removeEventListener('change', onChange)
  }, [query])
  return matches
}

export const useIsMobile = () => useMediaQuery('(max-width: 767px)')
