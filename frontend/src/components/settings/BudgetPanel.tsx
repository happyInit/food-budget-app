import { useEffect, useState } from 'react'
import { useBudget, useExpenseSummary, usePutBudget } from '../../lib/queries'
import { parseAmount, presetToAmount } from '../../lib/auth'
import { won } from '../../lib/api'

const presets = ['20만', '30만', '40만', '50만']
const now = new Date()
const MONTH = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`

// 월 식비 예산 설정/변경 폼 — 온보딩(/budget)과 마이·홈 모달에서 공용.
// 현재 예산으로 시드(하드코딩 X) · 최초/변경 버튼 라벨 분기 · 저장 시 홈/식비 즉시 반영(usePutBudget이 ['expense']도 무효화).
export default function BudgetPanel({ onSaved }: { onSaved?: () => void }) {
  const { data: budget } = useBudget()
  const { data: summary } = useExpenseSummary(MONTH)
  const putM = usePutBudget()

  const existing = budget?.amount ?? null
  const [amount, setAmount] = useState<number>(existing ?? 300000)
  const [touched, setTouched] = useState(false)

  // 예산이 뒤늦게 로드되면(캐시 미스) 사용자가 아직 안 건드린 경우 현재값으로 시드.
  useEffect(() => {
    if (!touched && existing != null) setAmount(existing)
  }, [existing, touched])

  const set = (v: number) => { setTouched(true); setAmount(v) }
  const save = () => {
    if (amount <= 0) return
    putM.mutate(amount, { onSuccess: () => onSaved?.() })
  }

  const spent = summary?.spent ?? 0
  const remaining = summary?.remaining ?? (existing != null ? existing - spent : 0)

  return (
    <div>
      {/* 현재 사용/잔여 — 이미 예산을 설정한 사람에게만(최초 설정엔 데이터 없음) */}
      {existing != null && (
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, marginBottom: 14, padding: '12px 14px', background: '#F7F7F7', fontSize: 12.5 }}>
          <span style={{ color: '#9A9A9A' }}>이번 달 사용 <b className="num" style={{ color: '#17264A' }}>{won(spent)}원</b></span>
          <span style={{ color: '#9A9A9A' }}>남은 예산 <b className="num" style={{ color: '#F26419' }}>{won(remaining)}원</b></span>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, border: '1.5px solid #F26419', padding: '14px 16px', background: '#FCEBDD' }}>
        <span style={{ fontSize: 22, fontWeight: 800, color: '#F26419' }}>₩</span>
        <input
          value={won(amount)}
          onChange={(e) => set(parseAmount(e.target.value))}
          inputMode="numeric"
          className="num"
          style={{ flex: 1, border: 'none', background: 'none', fontSize: 28, fontWeight: 800, color: '#17264A', outline: 'none', textAlign: 'right', minWidth: 0 }}
        />
        <span style={{ fontSize: 15, color: '#5E5E5E', fontWeight: 600 }}>원</span>
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
        {presets.map((p) => {
          const val = presetToAmount(p)
          const on = val === amount
          return (
            <button key={p} onClick={() => set(val)} style={{ flex: 1, padding: 9, border: on ? '1.5px solid #F26419' : '1px solid #E6E6E6', background: on ? '#FCEBDD' : '#fff', fontSize: 13, fontWeight: on ? 700 : 600, color: on ? '#F26419' : '#5E5E5E', cursor: 'pointer' }}>{p}</button>
          )
        })}
      </div>

      {putM.isError && (
        <div style={{ marginTop: 12, fontSize: 12, color: '#F04452' }}>예산 저장에 실패했어요. 로그인 상태를 확인해주세요.</div>
      )}

      <button
        onClick={save}
        disabled={putM.isPending}
        style={{ width: '100%', padding: 14, marginTop: 16, border: 'none', background: '#F26419', color: '#fff', fontSize: 15, fontWeight: 700, cursor: putM.isPending ? 'default' : 'pointer', opacity: putM.isPending ? 0.6 : 1 }}
      >
        {putM.isPending ? '저장 중…' : existing != null ? '예산 변경' : '시작하기'}
      </button>
    </div>
  )
}
