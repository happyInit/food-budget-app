import { useNavigate } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { recipeDetail as d } from '../lib/mock'
import { Card, Chip, Thumb, Button } from '../components/ui'

export default function RecipeDetail() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-5xl px-4 py-4 md:px-7 md:py-6">
      <button onClick={() => nav(-1)} className="mb-3 flex items-center gap-1 text-sm font-semibold text-sub">
        <ChevronLeft size={18} /> 뒤로
      </button>
      <div className="grid gap-5 md:grid-cols-[1fr_360px] md:items-start">
        <div>
          <div className="grid h-48 place-items-center rounded-2xl bg-[radial-gradient(120%_120%_at_15%_0%,#f6efe1,#e7dcc6)] text-7xl">
            {d.emoji}
          </div>
          <h1 className="mt-4 text-2xl font-extrabold tracking-tight">{d.name}</h1>
          <p className="num mt-1 text-sm text-sub">
            냉장고 대파·두부를 오늘 안에 · {d.min}분 · {d.serv}인분 · {d.level}
          </p>
          <h2 className="mb-3 mt-7 text-lg font-extrabold">조리 순서</h2>
          <ol>
            {d.steps.map((s, i) => (
              <li key={i} className="flex gap-3.5 border-b border-line/60 py-3.5 text-[15px] text-[#3a3835]">
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-ink text-xs font-extrabold text-white">
                  {i + 1}
                </span>
                {s}
              </li>
            ))}
          </ol>
        </div>
        <Card className="p-5 md:sticky md:top-20">
          <div className="flex items-center justify-between">
            <b className="text-base">재료</b>
            <span className="text-xs text-faint">{d.serv}인 기준</span>
          </div>
          <div className="mt-2">
            {d.ingredients.map((g, i) => (
              <div
                key={i}
                className={`flex items-center gap-3 py-2.5 ${i > 0 ? 'border-t border-line/60' : ''} ${
                  g.state === '보유' ? 'opacity-60' : ''
                }`}
              >
                <Thumb className="h-9 w-9 text-lg">{g.emoji}</Thumb>
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-bold">{g.name}</div>
                  <div className="text-xs text-sub">
                    <Chip tone={g.state === '부족' ? 'danger' : 'brand'}>{g.state}</Chip> {g.store}
                  </div>
                </div>
                {g.price ? <span className="num text-sm font-extrabold">{g.price}</span> : <Chip>보유</Chip>}
              </div>
            ))}
          </div>
          <div className="my-3.5 flex items-center justify-between rounded-xl bg-brand-weak px-4 py-3">
            <span className="text-[13px] font-bold text-brand">부족 2개 합계</span>
            <span className="num font-extrabold text-brand">{d.total}</span>
          </div>
          <Button size="lg" className="w-full" onClick={() => nav('/cart')}>
            장바구니 담기
          </Button>
          <Button variant="line" className="mt-2.5 w-full">
            📖 레시피북 저장
          </Button>
        </Card>
      </div>
    </div>
  )
}
