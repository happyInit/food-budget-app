import { won } from '../lib/api'
import { useExpenseBreakdown, useExpenseSummary, usePantryStats } from '../lib/queries'
import type { ExpenseCategory } from '../lib/api'

const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }

// 카테고리 표시 라벨/색 — 성과보기 '식비 구성'.
const CAT: Record<ExpenseCategory, { label: string; c: string }> = {
  GROCERY: { label: '집밥 (장보기)', c: '#1E5F96' },
  DINING: { label: '외식', c: '#F26419' },
  DELIVERY: { label: '배달', c: '#F04452' },
  ETC: { label: '기타', c: '#17264A' },
}

// 이번 달(YYYY-MM) — 실 날짜 기준. month prop 없으면 현재 달.
const now = new Date()
const CUR_MONTH = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`

// 성과지표 콘텐츠 (시트/페이지 공용) — 전부 실 유저 데이터. 헤더는 감싸는 쪽에서 처리.
export default function PerformancePanel({ month = CUR_MONTH }: { month?: string }) {
  const { data: summary } = useExpenseSummary(month)
  const { data: breakdown } = useExpenseBreakdown(month)
  const { data: pantry } = usePantryStats() // 안 버린 재료는 전체 기간 누적

  // ── 예산 잔여(도넛) + 월말 절약 예상 ──
  const hasBudget = summary?.budget != null
  const spent = summary?.spent ?? 0
  const budget = summary?.budget ?? 0
  const remaining = summary?.remaining ?? 0
  const remainPct = hasBudget && budget > 0 ? Math.max(0, Math.min(100, Math.round((remaining / budget) * 100))) : 0
  // 현재 페이스로 월말까지 갔을 때 예상 잔여(지출/경과일 × 총일수).
  const [y, m] = month.split('-').map(Number)
  const isCurMonth = month === CUR_MONTH
  const daysInMonth = new Date(y, m, 0).getDate()
  const elapsed = isCurMonth ? now.getDate() : daysInMonth
  const projectedSpend = elapsed > 0 ? Math.round((spent / elapsed) * daysInMonth) : spent
  const projected = budget - projectedSpend // + 절약 / − 초과
  const donutDeg = Math.round((remainPct / 100) * 360)

  // ── 냉장고 성과(안 버린/버린 재료·실천율) ──
  const consumed = pantry?.consumed ?? 0
  const discarded = pantry?.discarded ?? 0
  const savedRate = pantry?.saved_rate != null ? Math.round(pantry.saved_rate * 100) : null

  // ── 식비 구성(카테고리) ──
  const total = breakdown?.total ?? 0
  const cats = breakdown?.categories ?? []
  const grocery = cats.find((c) => c.category === 'GROCERY')
  const homePct = total > 0 && grocery ? Math.round(grocery.ratio * 100) : null
  const spentCats = cats.filter((c) => c.amount > 0)

  // [값, 라벨, 글자색, 배경, 설명(툴팁)]. '소비 실천율'=설계의 '안 버린 재료 %'. 냉장고 먹음/버림 처리로 채워짐.
  const tiles: [string, string, string, string, string][] = [
    [`${consumed}종`, '안 버린 재료', '#1E5F96', '#E7EFF8', '먹어서 소비한 재료 종류 수 (버리지 않음)'],
    [`${discarded}종`, '버린 재료', '#F04452', '#FDECEC', '소비기한 경과·미사용으로 폐기한 재료 종류 수'],
    [savedRate == null ? '—' : `${savedRate}%`, '소비 실천율', '#F26419', '#FCEBDD', '먹은 재료 ÷ (먹은 + 버린) — 재료를 버리지 않고 소비한 비율. 냉장고에서 재료를 먹음/버림으로 정리하면 채워져요'],
    [homePct == null ? '—' : `${homePct}%`, '집밥 비중', '#17264A', '#F7F7F7', '전체 식비 중 집밥(장보기) 지출 비율'],
  ]

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{ padding: '6px 12px', fontSize: 12.5, fontWeight: 700, border: '1.5px solid #F26419', background: '#FCEBDD', color: '#F26419' }}>{y}년 {m}월</span>
        <span style={{ fontSize: 12, color: '#9A9A9A' }}>내 지출·냉장고 기록 기반</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 16 }}>
        {/* 도넛 — 예산 잔여 */}
        <div style={{ ...card, padding: 24, textAlign: 'center' }}>
          <div style={{ width: 150, height: 150, borderRadius: '50%', background: `conic-gradient(#1E5F96 0deg ${donutDeg}deg,#EFEFEF ${donutDeg}deg)`, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 14px' }}>
            <div style={{ width: 112, height: 112, borderRadius: '50%', background: '#fff', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
              <div style={{ fontSize: 28, fontWeight: 800, color: '#1E5F96' }}>{hasBudget ? `${remainPct}%` : '—'}</div>
              <div style={{ fontSize: 11, color: '#9A9A9A' }}>예산 잔여</div>
            </div>
          </div>
          {hasBudget ? (
            <>
              <div style={{ fontSize: 14, fontWeight: 700 }}>{projected >= 0 ? '예산 달성 순항 중' : '예산 초과 주의'}</div>
              <div style={{ fontSize: 12.5, color: '#9A9A9A', marginTop: 4 }}>
                이 페이스면 월말 <b style={{ color: projected >= 0 ? '#1E5F96' : '#F04452' }}>{projected >= 0 ? '+' : '−'}{won(Math.abs(projected))}원</b> {projected >= 0 ? '절약 예상' : '초과 예상'}
              </div>
            </>
          ) : (
            <>
              <div style={{ fontSize: 14, fontWeight: 700 }}>예산 미설정</div>
              <div style={{ fontSize: 12.5, color: '#9A9A9A', marginTop: 4 }}>이번 달 예산을 정하면 잔여·절약 예상을 보여줘요</div>
            </>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* 이번 달 성과 4종 */}
          <div style={card}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 14px' }}>이번 달 성과</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {tiles.map(([v, k, c, bg, tip]) => (
                <div key={k} title={tip} style={{ background: bg, padding: 14, cursor: 'help' }}>
                  <div className="num" style={{ fontSize: 22, fontWeight: 800, color: c }}>{v}</div>
                  <div style={{ fontSize: 12, color: '#5E5E5E', marginTop: 2 }}>{k}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 식비 구성 (카테고리별 실 지출) */}
          <div style={card}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>식비 구성</h3>
            {total === 0 ? (
              <div style={{ fontSize: 13, color: '#9A9A9A', padding: '8px 0' }}>아직 이번 달 지출 기록이 없어요.</div>
            ) : (
              spentCats.map((c) => (
                <div key={c.category} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', fontSize: 13, borderTop: '1px solid #EFEFEF' }}>
                  <span><b style={{ color: CAT[c.category].c }}>●</b> {CAT[c.category].label}</span>
                  <span className="num" style={{ fontWeight: 600 }}>{won(c.amount)}원 · {Math.round(c.ratio * 100)}%</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
