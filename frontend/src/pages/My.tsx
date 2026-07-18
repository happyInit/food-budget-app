import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBookmarks, useBudget, useExcludedItems, useExpenseSummary, useLogout, useMe, useMyRecipes, usePantryStats } from '../lib/queries'
import { won } from '../lib/api'
import Modal from '../components/Modal'
import BudgetPanel from '../components/settings/BudgetPanel'
import ExcludedItemsPanel from '../components/settings/ExcludedItemsPanel'
import NotificationSettingsPanel from '../components/settings/NotificationSettingsPanel'
import AccountPanel from '../components/settings/AccountPanel'

type MyModal = null | 'budget' | 'excluded' | 'notif' | 'account'

const PROVIDER: Record<string, string> = { local: '이메일 로그인', kakao: '카카오 로그인', google: '구글 로그인' }

const now = new Date()
const MONTH = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`

export default function My() {
  const nav = useNavigate()
  const { data: me } = useMe() // GET /api/users/me (#7) — 토큰 있을 때만
  const { data: budget } = useBudget() // GET /api/users/budget (#9)
  const { data: summary } = useExpenseSummary(MONTH) // 예산 잔여 %
  const { data: pantry } = usePantryStats() // 안 버린 재료·소비 실천율
  const { data: books } = useBookmarks() // 담은 레시피(북마크)
  const { data: mine } = useMyRecipes() // 내가 만든 레시피
  const { data: excluded } = useExcludedItems() // 제외 재료 개수
  const logout = useLogout()
  const [modal, setModal] = useState<MyModal>(null)

  const nickname = me?.nickname ?? '게스트'
  const providerLabel = me ? (PROVIDER[me.provider] ?? me.provider) : '로그인이 필요해요'
  const budgetLabel = budget ? `${won(budget.amount)}원 ›` : '미설정 ›'
  const bookCount = (books?.books.length ?? 0) + (mine?.recipes.length ?? 0)   // 담은 + 내가 만든
  const excludedCount = excluded?.length ?? 0

  // 실 통계 (성과보기와 동일 정의) — 데이터 없으면 '—'.
  const hasBudget = summary?.budget != null
  const remainPct = hasBudget && summary!.budget! > 0
    ? Math.max(0, Math.min(100, Math.round(((summary!.remaining ?? 0) / summary!.budget!) * 100)))
    : null
  const consumed = pantry?.consumed ?? 0
  const savedRate = pantry?.saved_rate != null ? Math.round(pantry.saved_rate * 100) : null
  const stats: [string, string, string, string][] = [
    [remainPct == null ? '—' : `${remainPct}%`, '예산 잔여', '#F26419', '이번 달 예산 중 남은 비율'],
    [`${consumed}종`, '안 버린 재료', '#17264A', '먹어서 소비한 재료 종류 수 (버리지 않음)'],
    [savedRate == null ? '—' : `${savedRate}%`, '소비 실천율', '#1E5F96', '먹은 재료 ÷ (먹은 + 버린) — 재료를 버리지 않고 소비한 비율. 냉장고에서 먹음/버림으로 정리하면 채워져요'],
  ]

  const rows: [string, string, boolean, (() => void)?][] = [
    ['월 식비 예산 설정', budgetLabel, true, () => setModal('budget')],
    ['제외 재료 설정', excludedCount ? `${excludedCount}개 ›` : '›', true, () => setModal('excluded')],
    ['내 레시피북', `${bookCount}개 ›`, true, () => nav('/recipebook')],
    ['알림 설정', '›', true, () => setModal('notif')],
    ['계정 관리', '›', true, () => setModal('account')],
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
          {/* 통계 — 식비요약(예산잔여) + 냉장고 통계(안버린재료·소비실천율) 실데이터 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            {stats.map(([v, k, c, tip]) => (
              <div key={k} title={tip} style={{ background: '#fff', border: '1px solid #E6E6E6', padding: 16, textAlign: 'center', cursor: 'help' }}>
                <div style={{ fontSize: 22, fontWeight: 800, color: c }}>{v}</div>
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

      <Modal open={modal === 'budget'} onClose={() => setModal(null)} title="월 식비 예산 설정">
        <BudgetPanel onSaved={() => setModal(null)} />
      </Modal>
      <Modal open={modal === 'excluded'} onClose={() => setModal(null)} title="제외 재료 설정">
        <ExcludedItemsPanel />
      </Modal>
      <Modal open={modal === 'notif'} onClose={() => setModal(null)} title="알림 설정">
        <NotificationSettingsPanel />
      </Modal>
      <Modal open={modal === 'account'} onClose={() => setModal(null)} title="계정 관리">
        <AccountPanel onClose={() => setModal(null)} />
      </Modal>
    </div>
  )
}
