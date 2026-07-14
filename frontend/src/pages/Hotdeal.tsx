import { useNavigate } from 'react-router-dom'
import { hotdeal as h } from '../lib/mock'
import { Card, Chip, Thumb, Button, Section } from '../components/ui'

export default function Hotdeal() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">핫딜</h1>
      <p className="mt-1 text-sm text-sub">
        오아시스 타임세일·마감세일을 모아 관련 레시피로 연결해요.{' '}
        <span className="text-faint">지금 싼 재료(시세추천)는 홈·장바구니에서.</span>
      </p>

      <Section title="⏱ 타임세일" more="매일 15시 리셋" />
      <div className="grid gap-3 md:grid-cols-3">
        {h.time.map((t) => (
          <Card key={t.name} className="overflow-hidden">
            <div className="relative grid h-28 place-items-center bg-[radial-gradient(120%_120%_at_15%_0%,#f6efe1,#e7dcc6)] text-5xl">
              {t.emoji}
              <span className="absolute left-2.5 top-2.5">
                <Chip tone="danger">{t.dl}</Chip>
              </span>
            </div>
            <div className="p-3.5">
              <div className="font-bold">{t.name}</div>
              <div className="text-xs text-sub">{t.sub}</div>
              <div className="mt-2.5 flex items-center justify-between">
                <span className="num font-extrabold">{t.price}</span>
                <Button size="sm">담기</Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Section title="🔥 마감세일" more="17시 오픈 · 오늘 마감" />
      <div className="grid gap-3 md:grid-cols-3">
        {h.close.map((c) => (
          <Card key={c.name} className="p-4">
            <div className="flex items-center gap-3">
              <Thumb>{c.emoji}</Thumb>
              <div className="min-w-0">
                <div className="font-bold">{c.name}</div>
                <div className="text-xs text-sub">{c.sub}</div>
              </div>
            </div>
            <div className="mt-3 flex items-end justify-between">
              <div>
                <span className="text-xs font-extrabold text-brand">{c.dl}</span>
                <div className="num font-extrabold">{c.price}</div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => nav('/recipes/kimchi')}>
                {c.recipe}
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
