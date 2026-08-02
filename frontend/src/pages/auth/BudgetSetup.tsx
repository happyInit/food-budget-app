import { useNavigate } from 'react-router-dom'
import AuthWrap, { authCard } from './AuthWrap'
import BudgetPanel from '../../components/settings/BudgetPanel'

// 가입 직후 온보딩 — 예산 설정 폼(BudgetPanel)을 온보딩 chrome 안에 재사용. 저장 시 홈으로.
export default function BudgetSetup() {
  const nav = useNavigate()
  return (
    <AuthWrap>
      <div style={{ textAlign: 'center', marginBottom: 24 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#F26419', letterSpacing: '1px' }}>STEP 1 / 1</div>
        <div style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', marginTop: 8 }}>한 달 식비 예산을 정해주세요</div>
        <div style={{ fontSize: 13, color: '#5E5E5E', marginTop: 10 }}>추천·장바구니 계산의 기준이 됩니다. 나중에 언제든 바꿀 수 있어요.</div>
      </div>
      <div style={authCard}>
        <div style={{ marginBottom: 16, padding: '12px 14px', background: '#E7EFF8', fontSize: 12.5, color: '#1E5F96', display: 'flex', alignItems: 'center', gap: 8 }}>
          가입 축하 <b>1,000P</b> 지급! 레시피 등록 시마다 추가 적립
        </div>
        <BudgetPanel onSaved={() => nav('/home')} />
      </div>
    </AuthWrap>
  )
}
