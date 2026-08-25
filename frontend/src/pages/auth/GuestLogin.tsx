import { useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import AuthWrap, { authCard, primaryBtn } from './AuthWrap'
import { useLogin } from '../../lib/queries'

// 시연용 게스트 자동 로그인. QR 한 번으로 바로 /home 까지 간다.
// 계정은 guest001~guest999 (비밀번호 = 아이디와 동일) 가 DB 에 실재한다.
const GUEST_MIN = 1
const GUEST_MAX = 999

// 🔴 번호를 무작위로 뽑는 이유: 같은 QR 을 여러 명이 동시에 찍는다.
//    한 계정을 공유하면 서로의 장바구니·예산이 섞여서 시연이 망가진다.
function pickGuestNo(asked: string | null): string {
  const n = Number(asked)
  const picked =
    Number.isInteger(n) && n >= GUEST_MIN && n <= GUEST_MAX
      ? n
      : GUEST_MIN + Math.floor(Math.random() * (GUEST_MAX - GUEST_MIN + 1))
  return String(picked).padStart(3, '0')
}

export default function GuestLogin() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const loginM = useLogin()
  // StrictMode 는 effect 를 두 번 돌린다 → 로그인 요청이 두 번 나가지 않게 잠근다.
  const fired = useRef(false)

  useEffect(() => {
    if (fired.current) return
    fired.current = true

    const id = pickGuestNo(params.get('n'))
    loginM.mutate(
      { email: `guest${id}@gmail.com`, password: `guest${id}` },
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
