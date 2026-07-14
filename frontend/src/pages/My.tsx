import { useNavigate } from 'react-router-dom'

export default function My() {
  const nav = useNavigate()
  const rows: [string, string, boolean, (() => void)?][] = [
    ['월 식비 예산 설정', '300,000원 ›', true],
    ['제외 재료 설정', '오이 외 1 ›', true],
    ['내 레시피북', '23개 ›', true, () => nav('/recipebook')],
    ['알림 설정', '›', true],
    ['계정 관리', '›', true],
    ['로그아웃', '›', false, () => nav('/login')],
  ]
  return (
    <div>
      <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: '0 0 18px' }}>마이페이지</h1>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 16 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ background: '#fff', border: '1px solid #E6E6E6', padding: 20, display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{ width: 60, height: 60, borderRadius: '50%', background: '#1FA463', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 26, color: '#fff', fontWeight: 800 }}>김</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 18, fontWeight: 800 }}>김자취</div>
              <div style={{ fontSize: 12.5, color: '#9A9A9A' }}>카카오 로그인 · 가입 3개월째</div>
            </div>
            <span style={{ padding: '5px 11px', fontSize: 12, fontWeight: 700, background: '#E6F6EC', color: '#1FA463' }}>1,000P</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            {[['61%', '예산 잔여', '#1FA463'], ['18', '요리 횟수', '#1A1A1A'], ['23%', '절약률', '#15B76E']].map(([v, k, c]) => (
              <div key={k} style={{ background: '#fff', border: '1px solid #E6E6E6', padding: 16, textAlign: 'center' }}>
                <div style={{ fontSize: 22, fontWeight: 800, color: c as string }}>{v}</div>
                <div style={{ fontSize: 11.5, color: '#9A9A9A' }}>{k}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ background: '#fff', border: '1px solid #E6E6E6', padding: '8px 20px' }}>
          {rows.map(([label, val, hasBorder, onClick], i) => (
            <div key={i} onClick={onClick} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 0', borderBottom: hasBorder ? '1px solid #EFEFEF' : 'none', fontSize: 14, cursor: 'pointer', color: label === '로그아웃' ? '#F04452' : '#1A1A1A' }}>
              <span>{label}</span>
              <span style={{ color: label === '로그아웃' ? '#F04452' : '#9A9A9A' }}>{val}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
