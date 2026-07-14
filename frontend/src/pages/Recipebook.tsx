import { useNavigate } from 'react-router-dom'
import { recipebook } from '../lib/mock'
import { Card, Chip, Button } from '../components/ui'

export default function Recipebook() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">내 레시피북</h1>
          <p className="mt-1 text-sm text-sub">저장·작성·추출한 레시피를 모아요.</p>
        </div>
        <Button onClick={() => nav('/youtube')}>＋ YouTube URL로 추출</Button>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {recipebook.map((r) => (
          <Card key={r.name} className="cursor-pointer overflow-hidden" onClick={() => nav('/recipes/' + r.id)}>
            <div className="relative grid h-28 place-items-center bg-[radial-gradient(120%_120%_at_15%_0%,#f6efe1,#e7dcc6)] text-5xl">
              {r.emoji}
              {r.tag && (
                <span className="absolute left-2.5 top-2.5">
                  <Chip tone="danger">{r.tag}</Chip>
                </span>
              )}
            </div>
            <div className="p-3.5">
              <div className="text-[15px] font-bold">{r.name}</div>
              <div className="mt-0.5 text-xs text-sub">{r.sub}</div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
