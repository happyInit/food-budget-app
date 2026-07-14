import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AuthLayout, { Field } from './AuthLayout'
import { Button } from '../../components/ui'

const PRESETS = ['30만', '46만', '60만', '직접입력']

export default function BudgetSetup() {
  const nav = useNavigate()
  const [sel, setSel] = useState('46만')
  return (
    <AuthLayout title="월 식비 예산을 정해요" sub="추천·장바구니 계산의 기준이 됩니다. 언제든 바꿀 수 있어요.">
      <Field label="이번 달 식비 예산">
        <div className="relative">
          <span className="absolute left-4 top-3 text-lg font-extrabold">₩</span>
          <input
            className="num w-full rounded-xl border border-line bg-surface py-3 pl-9 pr-4 text-xl font-extrabold outline-none focus:border-brand focus:ring-2 focus:ring-brand-weak"
            defaultValue="460,000"
          />
        </div>
      </Field>
      <div className="mb-6 mt-1 flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button
            key={p}
            onClick={() => setSel(p)}
            className={`rounded-full border px-4 py-2 text-sm font-bold ${
              sel === p ? 'border-ink bg-ink text-white' : 'border-line bg-surface text-sub'
            }`}
          >
            {p}
          </button>
        ))}
      </div>
      <Button size="lg" className="w-full" onClick={() => nav('/home')}>
        시작하기
      </Button>
      <p className="mt-4 text-center text-xs text-faint">1인가구 평균 식비는 월 40~50만원이에요.</p>
    </AuthLayout>
  )
}
