import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search } from 'lucide-react'
import { recipes, recipeFilters } from '../lib/mock'
import { Card, Chip } from '../components/ui'

export default function RecipeSearch() {
  const nav = useNavigate()
  const [f, setF] = useState(0)
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">레시피</h1>
      <p className="mt-1 text-sm text-sub">냉장고 재료·예산으로 걸러서 오늘 만들 걸 찾아보세요.</p>
      <div className="mt-4 flex items-center gap-2 rounded-full border border-line bg-surface px-4 py-2.5 text-sm text-faint">
        <Search size={16} /> 찌개, 계란, 돼지고기…
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {recipeFilters.map((x, i) => (
          <button
            key={x}
            onClick={() => setF(i)}
            className={`rounded-full border px-3.5 py-1.5 text-sm font-bold ${
              f === i ? 'border-ink bg-ink text-white' : 'border-line bg-surface text-sub'
            }`}
          >
            {x}
          </button>
        ))}
      </div>
      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {recipes.map((r) => (
          <Card key={r.id} className="cursor-pointer overflow-hidden" onClick={() => nav('/recipes/' + r.id)}>
            <div className="grid h-28 place-items-center bg-[radial-gradient(120%_120%_at_15%_0%,#f6efe1,#e7dcc6)] text-5xl">
              {r.emoji}
            </div>
            <div className="p-3.5">
              <div className="text-[15px] font-bold">{r.name}</div>
              <div className="num mt-0.5 text-xs text-sub">
                {r.min}분 · 보유 {r.have}/{r.total}
              </div>
              <div className="mt-2">
                <Chip tone={r.tone}>{r.tag}</Chip>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
