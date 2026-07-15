import { useState } from 'react'
import { inp, lab, primaryBtn, ghostBtn } from './formStyles'
import { useAddExpense } from '../../lib/queries'
import type { ExpenseCategory } from '../../lib/api'

// UI 라벨 → API enum (mealplan.expense.category CHECK)
const CATS: { label: string; value: ExpenseCategory }[] = [
  { label: '장보기', value: 'GROCERY' },
  { label: '외식', value: 'DINING' },
  { label: '배달', value: 'DELIVERY' },
  { label: '기타', value: 'ETC' },
]

const today = () => new Date().toISOString().slice(0, 10)

// 지출 직접 기록 (모달 콘텐츠) — mealplan #39 POST /api/expenses.
export default function ExpenseAddForm({ onDone }: { onDone: () => void }) {
  const [cat, setCat] = useState<ExpenseCategory>('DINING')
  const [spentOn, setSpentOn] = useState(today())
  const [memo, setMemo] = useState('')
  const [amount, setAmount] = useState('')
  const add = useAddExpense()

  const amountNum = Number(amount.replace(/[^0-9]/g, ''))
  const valid = amountNum > 0 && /^\d{4}-\d{2}-\d{2}$/.test(spentOn)

  const save = () => {
    if (!valid) return
    add.mutate(
      { amount: amountNum, category: cat, spent_on: spentOn, memo: memo || null, source: 'MANUAL' },
      { onSuccess: onDone },
    )
  }

  return (
    <div>
      <label style={lab}>날짜</label>
      <input value={spentOn} onChange={(e) => setSpentOn(e.target.value)} type="date" style={inp} />
      <label style={lab}>분류</label>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '8px 0 16px' }}>
        {CATS.map((c) => {
          const on = c.value === cat
          return (
            <span key={c.value} onClick={() => setCat(c.value)} style={{ padding: '8px 13px', fontSize: 13, fontWeight: on ? 700 : 600, border: on ? '1.5px solid #F26419' : '1.5px solid #E6E6E6', background: on ? '#FCEBDD' : '#fff', color: on ? '#F26419' : '#5E5E5E', cursor: 'pointer' }}>{c.label}</span>
          )
        })}
      </div>
      <label style={lab}>내용</label>
      <input value={memo} onChange={(e) => setMemo(e.target.value)} placeholder="예: 김밥천국 점심" style={inp} />
      <label style={lab}>금액</label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '6px 0 12px', border: '1.5px solid #E6E6E6', padding: '11px 13px' }}>
        <input
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          inputMode="numeric"
          placeholder="7,000"
          className="num"
          style={{ flex: 1, border: 'none', outline: 'none', fontSize: 16, fontWeight: 700, textAlign: 'right', minWidth: 0 }}
        />
        <span style={{ fontSize: 14, color: '#5E5E5E' }}>원</span>
      </div>
      {add.error && <div style={{ color: '#F04452', fontSize: 12.5, marginBottom: 12 }}>{add.error.message}</div>}
      <div style={{ display: 'flex', gap: 10 }}>
        <button onClick={onDone} style={{ ...ghostBtn, flex: 1 }}>취소</button>
        <button onClick={save} disabled={!valid || add.isPending} style={{ ...primaryBtn, flex: 2, opacity: !valid || add.isPending ? 0.6 : 1, cursor: !valid || add.isPending ? 'not-allowed' : 'pointer' }}>
          {add.isPending ? '저장 중…' : '저장'}
        </button>
      </div>
    </div>
  )
}
