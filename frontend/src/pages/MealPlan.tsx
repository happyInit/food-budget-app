import { useNavigate } from 'react-router-dom'
import { mealPlan } from '../lib/mock'
import { Card, Chip, Thumb, Button } from '../components/ui'

export default function MealPlan() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">뭐 해먹지 · 뭐 사지</h1>
      <p className="mt-1 text-sm text-sub">냉장고 재고·유통기한·예산·제외 재료를 반영한 추천이에요.</p>
      <div className="mt-4 flex flex-wrap gap-2">
        {['🧊 임박 우선', '💸 저비용', '🍱 며칠치 플랜', '제외: 오이·가지'].map((x, i) => (
          <span
            key={x}
            className={`rounded-full border px-3.5 py-1.5 text-sm font-bold ${
              i === 0 ? 'border-ink bg-ink text-white' : 'border-line bg-surface text-sub'
            }`}
          >
            {x}
          </span>
        ))}
      </div>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {mealPlan.map((m) => (
          <Card key={m.name} className="p-4">
            <div className="flex items-center gap-3">
              <Thumb>{m.emoji}</Thumb>
              <div className="min-w-0">
                <div className="font-bold">{m.name}</div>
                <div className="text-xs text-sub">{m.sub}</div>
              </div>
            </div>
            <div className="my-3 flex gap-1.5">
              <Chip tone="brand">보유 {m.have}</Chip>
              <Chip tone={m.short > 0 ? 'danger' : 'n'}>부족 {m.short}</Chip>
            </div>
            <div className="flex items-center justify-between">
              <span className={`num font-extrabold ${m.short === 0 ? 'text-brand' : ''}`}>{m.add}</span>
              <Button size="sm" onClick={() => nav('/cart')}>
                담기
              </Button>
            </div>
          </Card>
        ))}
      </div>
      <Card className="mt-5 border-dashed border-brand bg-brand-weak/30 p-4 text-sm text-brand">
        🤖 <b>대화형 어시스턴트</b>로 "이번 주 3만원으로 3일치 저녁" 같은 플랜도 만들 수 있어요.{' '}
        <button onClick={() => nav('/assistant')} className="font-extrabold underline">
          어시스턴트 열기 →
        </button>
      </Card>
    </div>
  )
}
