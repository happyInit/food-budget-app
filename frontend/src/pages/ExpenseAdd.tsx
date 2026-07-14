import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Button } from '../components/ui'
import { inputCls, Field } from './auth/AuthLayout'

export default function ExpenseAdd() {
  const nav = useNavigate()
  const [c, setC] = useState('외식')
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">지출 추가</h1>
      <p className="mt-1 text-sm text-sub">영수증 외 외식·배달 등을 직접 기록해요.</p>
      <Card className="mt-5 max-w-md p-5">
        <Field label="금액">
          <div className="relative">
            <span className="absolute left-4 top-3 text-lg font-extrabold">₩</span>
            <input
              className="num w-full rounded-xl border border-line bg-surface py-3 pl-9 pr-4 text-xl font-extrabold outline-none focus:border-brand"
              defaultValue="12,000"
            />
          </div>
        </Field>
        <Field label="분류">
          <div className="flex flex-wrap gap-2">
            {['장보기', '외식', '배달', '기타'].map((x) => (
              <button
                key={x}
                onClick={() => setC(x)}
                className={`rounded-full border px-4 py-2 text-sm font-bold ${
                  c === x ? 'border-ink bg-ink text-white' : 'border-line bg-surface text-sub'
                }`}
              >
                {x}
              </button>
            ))}
          </div>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="날짜">
            <input className={inputCls} type="date" />
          </Field>
          <Field label="메모 (선택)">
            <input className={inputCls} placeholder="점심 김밥" />
          </Field>
        </div>
        <Button size="lg" className="w-full" onClick={() => nav('/expense')}>
          저장
        </Button>
      </Card>
    </div>
  )
}
