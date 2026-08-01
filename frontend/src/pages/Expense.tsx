import { useState } from 'react'
import { won } from '../lib/api'
import { useExpenseCalendar, useExpenseSummary, usePriceTrends } from '../lib/queries'
import Modal from '../components/Modal'
import ExpenseAddForm from '../components/forms/ExpenseAddForm'
import PerformancePanel from '../components/PerformancePanel'

const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6' }
const WEEK = ['일', '월', '화', '수', '목', '금', '토']

// 현재 달(YYYY-MM) + 오늘 — 실 날짜 기준
const now = new Date()
const MONTH = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
const [Y, M] = [now.getFullYear(), now.getMonth()] // M=0-based
const TODAY = now.getDate()
const daysInMonth = new Date(Y, M + 1, 0).getDate()
const firstWeekday = new Date(Y, M, 1).getDay()

// 캘린더 셀 금액 축약 (11,200 → 11.2k)
const compact = (n: number) => (n >= 10000 ? `${Math.round(n / 1000)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n))

// 일별 최저가 배열 → SVG 폴리라인 좌표(viewBox 0 0 72 24). 각 스파크라인을 자기 min~max로 정규화.
// 값이 클수록 화면 위(y 작게), 상하 2px 여백. 평평하면(변동 0) 중앙 직선.
function sparkPoints(prices: number[]): string {
  const n = prices.length
  if (n === 0) return ''
  const min = Math.min(...prices), max = Math.max(...prices), span = max - min
  return prices
    .map((p, i) => {
      const x = n === 1 ? 0 : (i / (n - 1)) * 72
      const y = span === 0 ? 12 : 22 - ((p - min) / span) * 20
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

export default function Expense() {
  const [modal, setModal] = useState<null | 'add' | 'perf'>(null)
  const { data: summary } = useExpenseSummary(MONTH)
  const { data: calendar, isLoading } = useExpenseCalendar(MONTH)
  const { data: trends, isLoading: trendsLoading } = usePriceTrends()
  const trendItems = trends?.items ?? []

  // 일별 금액 맵 (date 'YYYY-MM-DD' → amount)
  const byDay: Record<number, number> = {}
  for (const d of calendar?.days ?? []) byDay[Number(d.date.slice(8, 10))] = d.amount
  const spent = summary?.spent ?? 0
  const hasBudget = summary?.budget != null
  const budget = summary?.budget ?? 0
  const remaining = summary?.remaining ?? 0
  const pct = hasBudget && budget > 0 ? Math.min(100, Math.round((spent / budget) * 100)) : 0
  const spentDays = (calendar?.days ?? []).length
  const avg = spentDays > 0 ? Math.round(spent / spentDays) : 0

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>식비관리</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setModal('perf')} style={{ padding: '10px 15px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>성과 보기</button>
          <button onClick={() => setModal('add')} style={{ padding: '10px 15px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>지출 기록</button>
        </div>
      </div>

      {/* 다크 예산 히어로 */}
      <div style={{ background: '#17264A', color: '#fff', padding: '24px 26px', marginBottom: 18, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 18 }}>
        <div>
          <div style={{ fontSize: 13, color: 'rgba(255,255,255,.6)', marginBottom: 8 }}>{M + 1}월 {hasBudget ? '남은 예산' : '지출'}</div>
          <div className="num" style={{ fontSize: 32, fontWeight: 800, letterSpacing: '-1px' }}>
            {won(hasBudget ? remaining : spent)}<span style={{ fontSize: 16, fontWeight: 600 }}>원</span>
          </div>
          <div style={{ fontSize: 12.5, color: '#F7A968', marginTop: 6, fontWeight: 600 }}>
            {hasBudget ? `예산 ${won(budget)}원 중 ${pct}% 사용` : '예산 잔여는 계정 연동 후 표시돼요'}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 190, maxWidth: 300 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: 'rgba(255,255,255,.55)', marginBottom: 6 }}>
            <span>지출 {won(spent)}원</span>
            <span>{hasBudget ? `예산 ${won(budget)}원` : `지출한 날 ${spentDays}일`}</span>
          </div>
          <div style={{ height: 9, background: 'rgba(255,255,255,.16)', overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${hasBudget ? pct : 0}%`, background: '#F26419' }} />
          </div>
        </div>
      </div>

      {/* 캘린더 */}
      <div style={{ ...card, padding: 26 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <span style={{ fontSize: 19, fontWeight: 800 }}>{Y}. {M + 1}</span>
          <span className="num" style={{ fontSize: 13, color: '#F26419', fontWeight: 700 }}>{won(spent)}원</span>
        </div>
        {isLoading && <div style={{ color: '#9A9A9A', fontSize: 13, padding: '8px 0' }}>불러오는 중…</div>}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7,1fr)', gap: 6, textAlign: 'center' }}>
          {WEEK.map((w) => (
            <div key={w} style={{ fontSize: 13.5, fontWeight: 700, color: '#9A9A9A', padding: '10px 0' }}>{w}</div>
          ))}
          {Array.from({ length: firstWeekday }, (_, i) => <div key={'b' + i} />)}
          {Array.from({ length: daysInMonth }, (_, i) => i + 1).map((d) => {
            const today = d === TODAY
            const sp = byDay[d]
            return (
              <div key={d} style={{ minHeight: 74, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontSize: today ? 12.5 : 17, background: today ? '#F26419' : 'transparent', color: today ? '#fff' : sp ? '#17264A' : '#B5B5B5', fontWeight: today ? 700 : 400 }}>
                {d}
                {sp != null && <span className="num" style={{ fontSize: today ? 9 : 11.5, color: today ? '#fff' : '#F26419', fontWeight: 700 }}>{compact(sp)}</span>}
              </div>
            )
          })}
        </div>
      </div>

      {/* 이번 달 요약 (실데이터) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12, marginTop: 16 }}>
        {[
          { k: `${M + 1}월 총 지출`, v: `${won(spent)}원`, c: '#F26419' },
          { k: '지출한 날', v: `${spentDays}일`, c: '#17264A' },
          { k: '하루 평균', v: `${won(avg)}원`, c: '#1E5F96' },
          { k: '예산 잔여', v: hasBudget ? `${won(remaining)}원` : '연동 예정', c: hasBudget ? '#1E5F96' : '#B5B5B5' },
        ].map((s) => (
          <div key={s.k} style={{ ...card, padding: 18 }}>
            <div className="num" style={{ fontSize: 22, fontWeight: 800, color: s.c }}>{s.v}</div>
            <div style={{ fontSize: 12, color: '#5E5E5E', marginTop: 4 }}>{s.k}</div>
          </div>
        ))}
      </div>

      {/* 값 내린 재료 — price 실데이터(최근 7일 최저가 하락률 큰 순, 예산 절약 관점) */}
      <h2 style={{ fontSize: 17, fontWeight: 800, margin: '28px 0 4px' }}>이번 주 값 내린 재료</h2>
      <div style={{ fontSize: 12, color: '#9A9A9A', marginBottom: 14 }}>최근 7일 최저가가 떨어진 재료 · 하락폭 순</div>
      <div style={{ ...card, padding: '6px 20px' }}>
        {trendItems.length === 0 ? (
          <div style={{ color: '#9A9A9A', fontSize: 13, padding: '18px 2px' }}>
            {trendsLoading ? '불러오는 중…' : '최근 7일 새 값이 내린 재료가 아직 없어요.'}
          </div>
        ) : (
          trendItems.map((t) => {
            const color = t.delta_pct > 0 ? '#F04452' : t.delta_pct < 0 ? '#1E5F96' : '#B5B5B5'
            const label = t.delta_pct === 0 ? '보합' : `${Math.abs(t.delta_pct)}%${t.delta_pct > 0 ? '↑' : '↓'}`
            return (
              <div key={t.item_id} style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '15px 0', borderTop: '1px solid #EFEFEF' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 700 }}>{t.name}</div>
                  <div style={{ fontSize: 12, color: '#9A9A9A', marginTop: 2 }}>평균 {won(t.avg)}원</div>
                </div>
                <svg viewBox="0 0 72 24" width="72" height="24" style={{ flexShrink: 0 }}>
                  <polyline points={sparkPoints(t.prices)} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <div style={{ textAlign: 'right', minWidth: 92 }}>
                  <div className="num" style={{ fontSize: 15, fontWeight: 800 }}>{won(t.current)}원</div>
                  <div className="num" style={{ fontSize: 12, fontWeight: 700, color }}>{label}</div>
                </div>
              </div>
            )
          })
        )}
      </div>

      <Modal open={modal === 'add'} onClose={() => setModal(null)} title="지출 직접 기록">
        <ExpenseAddForm onDone={() => setModal(null)} />
      </Modal>
      <Modal open={modal === 'perf'} onClose={() => setModal(null)} title="성과지표" variant="sheet">
        <PerformancePanel />
      </Modal>
    </div>
  )
}
