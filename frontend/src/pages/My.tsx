import { useNavigate } from 'react-router-dom'
import { useBudget, useLogout, useMe } from '../lib/queries'
import { won } from '../lib/api'

const PROVIDER: Record<string, string> = { local: '이메일 로그인', kakao: '카카오 로그인', google: '구글 로그인' }

export default function My() {
  const nav = useNavigate()
  const { data: me } = useMe() // GET /api/users/me (#7) — 토큰 있을 때만
  const { data: budget } = useBudget() // GET /api/users/budget (#9)
  const logout = useLogout()

  const nickname = me?.nickname ?? '게스트'
  const providerLabel = me ? (PROVIDER[me.provider] ?? me.provider) : '로그인이 필요해요'
  const budgetLabel = budget ? `${won(budget.amount)}원 ›` : '미설정 ›'

  const rows: [string, string, boolean, (() => void)?][] = [
    ['월 식비 예산 설정', budgetLabel, true, () => nav('/budget')],
    ['제외 재료 설정', '오이 외 1 ›', true],
    ['내 레시피북', '23개 ›', true, () => nav('/recipebook')],
    ['알림 설정', '›', true],
    ['계정 관리', '›', true],
    ['로그아웃', '›', false, async () => { await logout(); nav('/login') }],
  ]
  return (
    <div>
      <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: '0 0 18px' }}>마이페이지</h1>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 16 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ background: '#fff', border: '1px solid #E6E6E6', padding: 20, display: 'flex', alignItems: 'center', gap: 16 }}>
            <div style={{ width: 60, height: 60, borderRadius: '50%', background: '#F26419', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 26, color: '#fff', fontWeight: 800 }}>{nickname.slice(0, 1)}</div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 18, fontWeight: 800 }}>{nickname}</div>
              <div style={{ fontSize: 12.5, color: '#9A9A9A' }}>{providerLabel}</div>
            </div>
            {/* 포인트는 타 서비스 데이터 — 아직 플레이스홀더 */}
            <span style={{ padding: '5px 11px', fontSize: 12, fontWeight: 700, background: '#FCEBDD', color: '#F26419' }}>1,000P</span>
          </div>
          {/* 통계는 Expense·MealPlan 데이터 — 아직 플레이스홀더 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            {[['61%', '예산 잔여', '#F26419'], ['18', '요리 횟수', '#17264A'], ['23%', '절약률', '#1E5F96']].map(([v, k, c]) => (
              <div key={k} style={{ background: '#fff', border: '1px solid #E6E6E6', padding: 16, textAlign: 'center' }}>
                <div style={{ fontSize: 22, fontWeight: 800, color: c as string }}>{v}</div>
                <div style={{ fontSize: 11.5, color: '#9A9A9A' }}>{k}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ background: '#fff', border: '1px solid #E6E6E6', padding: '8px 20px' }}>
          {rows.map(([label, val, hasBorder, onClick], i) => (
            <div key={i} onClick={onClick} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 0', borderBottom: hasBorder ? '1px solid #EFEFEF' : 'none', fontSize: 14, cursor: 'pointer', color: label === '로그아웃' ? '#F04452' : '#17264A' }}>
              <span>{label}</span>
              <span style={{ color: label === '로그아웃' ? '#F04452' : '#9A9A9A' }}>{val}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
