import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import AuthWrap from './AuthWrap'
import { consumeState, redirectUri, type Provider } from '../../lib/oauth'
import { kakaoLogin, googleLogin, setToken, setRefreshToken, getBudget } from '../../lib/api'

const isProvider = (p?: string): p is Provider => p === 'kakao' || p === 'google'

// provider 리다이렉트 착지점(/auth/:provider/callback). code+state 를 받아 백엔드 교환 → 토큰 저장 → 이동.
// ⚠️ React Query 뮤테이션을 쓰지 않는다 — StrictMode 이중실행에서 mutate 콜백/옵저버 상태가
//    유실돼 "로그인 중"에 멈추는 버그가 있었음. 교환~이동을 한 이펙트 클로저에서 직접 처리(ran 가드로 1회).
export default function OAuthCallback() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const { provider } = useParams()
  const [sp] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  const ran = useRef(false)

  useEffect(() => {
    if (ran.current) return // code 는 1회용 — 교환 1회만(StrictMode 이중실행 방지)
    ran.current = true

    if (!isProvider(provider)) { setError('알 수 없는 로그인 제공자예요.'); return }
    if (sp.get('error')) { setError('로그인이 취소되었어요.'); return }
    const code = sp.get('code')
    if (!code) { setError('인증 코드를 받지 못했어요.'); return }
    if (!consumeState(provider, sp.get('state'))) {
      setError('보안 검증에 실패했어요. 다시 시도해주세요.'); return
    }

    ;(async () => {
      try {
        const tok = provider === 'kakao'
          ? await kakaoLogin(code, redirectUri(provider))
          : await googleLogin(code, redirectUri(provider))
        setToken(tok.access_token)       // 이후 '인증 O' API에 자동 첨부
        setRefreshToken(tok.refresh_token) // access(30분) 만료 시 silent 재발급
        qc.invalidateQueries()            // me·budget 등 유저-스코프 재조회
        // 예산 미설정(신규) → 예산 설정, 있으면 홈
        let hasBudget = false
        try { hasBudget = !!(await getBudget()) } catch { /* 무시 → /budget */ }
        nav(hasBudget ? '/home' : '/budget', { replace: true })
      } catch {
        setError('로그인 처리에 실패했어요. 다시 시도해주세요.')
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 마운트 1회만(code 1회용)
  }, [])

  return (
    <AuthWrap>
      <div style={{ textAlign: 'center', padding: '48px 0' }}>
        {error ? (
          <>
            <div style={{ fontSize: 14.5, color: '#F04452', marginBottom: 18, lineHeight: 1.6 }}>{error}</div>
            <button
              onClick={() => nav('/login', { replace: true })}
              style={{ padding: '11px 22px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}
            >
              로그인으로 돌아가기
            </button>
          </>
        ) : (
          <div style={{ fontSize: 15, color: '#5E5E5E' }}>로그인 중이에요…</div>
        )}
      </div>
    </AuthWrap>
  )
}
