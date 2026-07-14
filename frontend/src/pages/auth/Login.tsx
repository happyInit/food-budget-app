import { useNavigate } from 'react-router-dom'
import AuthWrap, { authCard } from './AuthWrap'

export default function Login() {
  const nav = useNavigate()
  return (
    <AuthWrap>
      <div style={{ textAlign: 'center', marginBottom: 30 }}>
        <img src="/icons/pug.png" alt="파그" style={{ width: 56, height: 56, borderRadius: '50%', objectFit: 'cover', display: 'block', margin: '0 auto' }} />
        <div style={{ fontSize: 24, fontWeight: 800, letterSpacing: '-.6px', marginTop: 10 }}>밀플래닝</div>
        <div style={{ fontSize: 14, color: '#5E5E5E', marginTop: 8, lineHeight: 1.6 }}>한 달 식비 예산 안에서<br />레시피·장보기·지출을 한 번에</div>
      </div>
      <div style={authCard}>
        <button style={{ width: '100%', padding: 13, border: 'none', background: '#FEE500', color: '#191600', fontSize: 14.5, fontWeight: 700, cursor: 'pointer' }}>카카오로 3초 만에 시작</button>
        <button onClick={() => nav('/login/email')} style={{ width: '100%', padding: 13, marginTop: 10, border: '1.5px solid #E6E6E6', background: '#fff', color: '#1A1A1A', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>이메일로 로그인</button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '18px 0', color: '#9A9A9A', fontSize: 12 }}>
          <div style={{ flex: 1, height: 1, background: '#E6E6E6' }} />처음이신가요?<div style={{ flex: 1, height: 1, background: '#E6E6E6' }} />
        </div>
        <button onClick={() => nav('/signup')} style={{ width: '100%', padding: 13, border: 'none', background: '#E6F6EC', color: '#1FA463', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>이메일로 회원가입</button>
      </div>
      <div style={{ textAlign: 'center', marginTop: 16, fontSize: 12, color: '#9A9A9A' }}>
        둘러보기만 할게요 · <a onClick={() => nav('/home')} style={{ cursor: 'pointer', fontWeight: 600 }}>데모 홈으로</a>
      </div>
    </AuthWrap>
  )
}
