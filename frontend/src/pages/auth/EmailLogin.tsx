import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AuthWrap, { authCard, inp, lab, primaryBtn } from './AuthWrap'
import { useLogin } from '../../lib/queries'

export default function EmailLogin() {
  const nav = useNavigate()
  const loginM = useLogin() // 성공 시 hook 내부에서 setToken → 이후 인증 API 자동 첨부
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const submit = () => {
    if (!email.trim() || !password) return
    loginM.mutate({ email: email.trim(), password }, { onSuccess: () => nav('/home') })
  }

  return (
    <AuthWrap>
      <div style={{ fontSize: 13, color: '#9A9A9A', marginBottom: 14, cursor: 'pointer' }} onClick={() => nav('/login')}>← 뒤로</div>
      <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-.5px', marginBottom: 20 }}>이메일 로그인</div>
      <div style={authCard}>
        <label style={lab}>이메일</label>
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="you@example.com"
          style={inp}
        />
        <label style={lab}>비밀번호</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="••••••••"
          style={{ ...inp, margin: '6px 0 6px' }}
        />
        {loginM.isError && (
          <div style={{ fontSize: 11.5, color: '#F04452', marginBottom: 8 }}>이메일 또는 비밀번호가 올바르지 않습니다.</div>
        )}
        <button
          onClick={submit}
          disabled={loginM.isPending}
          style={{ ...primaryBtn, marginTop: 8, opacity: loginM.isPending ? 0.6 : 1 }}
        >
          {loginM.isPending ? '로그인 중…' : '로그인'}
        </button>
        <div style={{ textAlign: 'center', marginTop: 14, fontSize: 12.5, color: '#9A9A9A' }}>비밀번호를 잊으셨나요? <a style={{ cursor: 'pointer', fontWeight: 600 }}>재설정</a></div>
      </div>
    </AuthWrap>
  )
}
