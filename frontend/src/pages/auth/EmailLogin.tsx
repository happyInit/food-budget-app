import { useNavigate } from 'react-router-dom'
import AuthWrap, { authCard, inp, lab, primaryBtn } from './AuthWrap'

export default function EmailLogin() {
  const nav = useNavigate()
  return (
    <AuthWrap>
      <div style={{ fontSize: 13, color: '#9A9A9A', marginBottom: 14, cursor: 'pointer' }} onClick={() => nav('/login')}>← 뒤로</div>
      <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-.5px', marginBottom: 20 }}>이메일 로그인</div>
      <div style={authCard}>
        <label style={lab}>이메일</label>
        <input placeholder="you@example.com" style={inp} />
        <label style={lab}>비밀번호</label>
        <input type="password" placeholder="••••••••" style={{ ...inp, margin: '6px 0 6px', border: '1.5px solid #F04452' }} />
        <div style={{ fontSize: 11.5, color: '#F04452', marginBottom: 14 }}>이메일 또는 비밀번호가 올바르지 않습니다.</div>
        <button onClick={() => nav('/home')} style={primaryBtn}>로그인</button>
        <div style={{ textAlign: 'center', marginTop: 14, fontSize: 12.5, color: '#9A9A9A' }}>비밀번호를 잊으셨나요? <a style={{ cursor: 'pointer', fontWeight: 600 }}>재설정</a></div>
      </div>
    </AuthWrap>
  )
}
