import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AuthWrap, { authCard, inp, lab, primaryBtn } from './AuthWrap'
import { useLogin, useSignup } from '../../lib/queries'
import { validateSignup } from '../../lib/auth'

// ⚠️ 이메일 인증(인증요청/인증번호) UI 제거 — 백엔드(account #2)는 email+password+nickname 직접 가입.
//    이메일 검증 도입 시(별도 과제) 여기에 단계 추가.
export default function Signup() {
  const nav = useNavigate()
  const signupM = useSignup()
  const loginM = useLogin()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [agreed, setAgreed] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const busy = signupM.isPending || loginM.isPending

  const submit = () => {
    const v = validateSignup({ email, password, nickname })
    if (v) return setErr(v)
    setErr(null)
    signupM.mutate(
      { email: email.trim(), password, nickname: nickname.trim() },
      {
        // 가입 성공 → 같은 자격으로 자동 로그인(토큰 저장) → 예산 설정으로
        onSuccess: () =>
          loginM.mutate(
            { email: email.trim(), password },
            { onSuccess: () => nav('/budget'), onError: () => nav('/login/email') },
          ),
        onError: (e) =>
          setErr((e as Error).message.includes('409') ? '이미 가입된 이메일이에요' : (e as Error).message),
      },
    )
  }

  return (
    <AuthWrap>
      <div style={{ fontSize: 13, color: '#9A9A9A', marginBottom: 14, cursor: 'pointer' }} onClick={() => nav('/login')}>← 뒤로</div>
      <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-.5px', marginBottom: 20 }}>회원가입</div>
      <div style={authCard}>
        <label style={lab}>이메일</label>
        <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" style={inp} />
        <label style={lab}>비밀번호</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="8자 이상" style={inp} />
        <label style={lab}>닉네임</label>
        <input value={nickname} onChange={(e) => setNickname(e.target.value)} placeholder="식비요정" style={inp} />
        <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12.5, color: '#5E5E5E', marginBottom: 12, cursor: 'pointer' }}>
          <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} style={{ marginTop: 2 }} />
          (필수) 서비스 이용약관 및 개인정보 처리방침에 동의합니다
        </label>
        {err && <div style={{ fontSize: 11.5, color: '#F04452', marginBottom: 12 }}>{err}</div>}
        <button onClick={submit} disabled={!agreed || busy} style={{ ...primaryBtn, opacity: !agreed || busy ? 0.6 : 1 }}>
          {busy ? '가입 중…' : '가입하고 예산 설정하기'}
        </button>
      </div>
    </AuthWrap>
  )
}
