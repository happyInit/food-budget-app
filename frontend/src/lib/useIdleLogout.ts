import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { getToken } from './api'
import { useLogout } from './queries'

// 30분 무입력 시 자동 로그아웃 → 랜딩. 요리 중 잠깐 자리를 비우는 사용을 감안해 넉넉히 잡음.
const IDLE_MS = 30 * 60 * 1000

// 인증 셸(AppShell)에서 1회 마운트. 활동(마우스·키·터치·스크롤)마다 타이머 리셋, 만료 시 로그아웃.
// 또한 api의 refresh 실패(하드 만료) 시 발행되는 'auth:expired' 이벤트도 받아 즉시 로그아웃한다.
export function useIdleLogout() {
  const nav = useNavigate()
  const logout = useLogout()
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    const doLogout = async () => {
      if (!getToken()) return // 이미 로그아웃 상태면 무시(중복 방지)
      await logout()
      nav('/', { replace: true })
    }
    const reset = () => {
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(doLogout, IDLE_MS)
    }
    const events: (keyof WindowEventMap)[] = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart']
    events.forEach((e) => window.addEventListener(e, reset, { passive: true }))
    window.addEventListener('auth:expired', doLogout)
    reset() // 최초 타이머 시작
    return () => {
      window.clearTimeout(timer.current)
      events.forEach((e) => window.removeEventListener(e, reset))
      window.removeEventListener('auth:expired', doLogout)
    }
  }, [nav, logout])
}
