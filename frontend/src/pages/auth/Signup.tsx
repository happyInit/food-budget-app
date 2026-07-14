import { useNavigate } from 'react-router-dom'
import AuthWrap, { authCard, inp, lab, primaryBtn } from './AuthWrap'

export default function Signup() {
  const nav = useNavigate()
  return (
    <AuthWrap>
      <div style={{ fontSize: 13, color: '#9A9A9A', marginBottom: 14, cursor: 'pointer' }} onClick={() => nav('/login')}>← 뒤로</div>
      <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-.5px', marginBottom: 20 }}>회원가입</div>
      <div style={authCard}>
        <label style={lab}>이메일</label>
        <div style={{ display: 'flex', gap: 8, margin: '6px 0 16px' }}>
          <input placeholder="you@example.com" style={{ ...inp, margin: 0, flex: 1, minWidth: 0 }} />
          <button style={{ padding: '0 14px', border: '1.5px solid #F26419', background: '#fff', color: '#F26419', fontSize: 13, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' }}>인증요청</button>
        </div>
        <label style={lab}>인증번호</label>
        <div style={{ display: 'flex', gap: 8, margin: '6px 0 16px', alignItems: 'center' }}>
          <input placeholder="6자리 숫자" style={{ ...inp, margin: 0, flex: 1, minWidth: 0 }} />
          <span className="num" style={{ fontSize: 12, color: '#1E5F96', fontWeight: 600, whiteSpace: 'nowrap' }}>03:58</span>
        </div>
        <label style={lab}>비밀번호</label>
        <input type="password" placeholder="8자 이상" style={inp} />
        <label style={lab}>닉네임</label>
        <input placeholder="식비요정" style={inp} />
        <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12.5, color: '#5E5E5E', marginBottom: 16, cursor: 'pointer' }}>
          <input type="checkbox" style={{ marginTop: 2 }} />(필수) 서비스 이용약관 및 개인정보 처리방침에 동의합니다
        </label>
        <button onClick={() => nav('/budget')} style={primaryBtn}>가입하고 예산 설정하기</button>
      </div>
    </AuthWrap>
  )
}
