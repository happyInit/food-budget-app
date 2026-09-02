import { useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import AuthWrap, { authCard, primaryBtn } from './AuthWrap'
import { useLogin } from '../../lib/queries'
import { guestCredentials } from '../../lib/guest'

// 시연용 게스트 자동 로그인. 링크·QR 한 번으로 바로 /home 까지 간다.
// 🔵 번호 규칙(무작위 001~999)은 `lib/guest.ts` 가 정본 — 랜딩의 「체험해보기」도 같은 것을 쓴다.

export default function GuestLogin() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const loginM = useLogin()
  // StrictMode 는 effect 를 두 번 돌린다 → 로그인 요청이 두 번 나가지 않게 잠근다.
  const fired = useRef(false)

  useEffect(() => {
    if (fired.current) return
    fired.current = true

    loginM.mutate(
      guestCredentials(params.get('n')),
      // replace: 뒤로가기로 이 화면에 돌아와 다시 로그인되는 것을 막는다.
      { onSuccess: () => nav('/home', { replace: true }) },
    )
  }, [])

  return (
    <AuthWrap>
      <div style={{ ...authCard, textAlign: 'center' }}>
        {loginM.isError ? (
          <>
            <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 8 }}>자동 로그인에 실패했습니다</div>
            <div style={{ fontSize: 13, color: '#7A7A7A', marginBottom: 18, lineHeight: 1.6 }}>
              잠시 후 다시 시도하거나
              <br />
              아래에서 직접 로그인해 주세요.
            </div>
            <button onClick={() => nav('/login/email')} style={primaryBtn}>
              이메일로 로그인
            </button>
          </>
        ) : (
          <>
            <div style={{ fontSize: 17, fontWeight: 800, marginBottom: 8 }}>체험 계정으로 입장 중…</div>
            <div style={{ fontSize: 13, color: '#7A7A7A', lineHeight: 1.6 }}>
              잠시만 기다려 주세요.
            </div>
          </>
        )}
      </div>
    </AuthWrap>
  )
}
