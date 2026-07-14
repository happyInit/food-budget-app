import { useNavigate } from 'react-router-dom'
import { homeData } from '../lib/mock'
import { Card, Chip, Bar, Section, Thumb, Button } from '../components/ui'

export default function Home() {
  const nav = useNavigate()
  const d = homeData

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <div className="text-xs font-bold text-brand">7월 · 남은 12일</div>
      <h1 className="mt-1 text-2xl font-extrabold tracking-tight md:text-[26px]">
        이번 달 식비, 잘 가고 있어요
      </h1>
      <p className="mt-1 text-sm text-sub">예산 잔여 · 냉장고 · 추천 · 지금 싼 재료를 한 곳에서.</p>

      {/* 예산 히어로 + stats */}
      <div className="mt-5 grid gap-4 md:grid-cols-[1.25fr_1fr]">
        <Card className="p-5">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-[13px] font-semibold text-sub">이번 달 남은 예산</div>
              <div className="num mt-1.5 text-[38px] font-extrabold leading-none">₩{d.budget.remaining}</div>
              <div className="num mt-1.5 text-[13px] text-faint">
                ₩{d.budget.total} 중 {d.budget.percent}% 남음
              </div>
            </div>
            <Chip tone="brand">절약 순항 중</Chip>
          </div>
          <div className="my-4">
            <Bar value={d.budget.percent} />
          </div>
          <div className="text-[13px] text-sub">
            하루 적정 <b className="num text-brand">₩{d.budget.daily}</b> · 이 페이스면{' '}
            <b>₩{d.budget.save} 절약</b> 예상
          </div>
        </Card>
        <div className="grid grid-cols-2 gap-3">
          {d.stats.map((s) => (
            <Card key={s.k} className="p-4">
              <div className="text-xs font-semibold text-sub">{s.k}</div>
              <div className="num mt-1.5 text-2xl font-extrabold">
                {s.v}
                <span className="text-sm text-faint">{s.unit}</span>
              </div>
              <div
                className={`mt-1 text-[11px] font-semibold ${
                  s.tone === 'warn' ? 'text-warn' : s.tone === 'brand' ? 'text-brand' : 'text-faint'
                }`}
              >
                {s.m}
              </div>
            </Card>
          ))}
        </div>
      </div>

      {/* 지금 싼 재료 */}
      <Section title="지금 싼 재료" more="핫딜 더보기 ›" onMore={() => nav('/hotdeal')} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {d.cheap.map((c) => (
          <Card key={c.name} className="p-4">
            <div className="flex items-center gap-3">
              <Thumb>{c.emoji}</Thumb>
              <div className="min-w-0">
                <div className="font-bold">{c.name}</div>
                <div className="text-xs text-sub">{c.sub}</div>
              </div>
            </div>
            <div className="mt-3.5 flex items-end justify-between">
              <div>
                <span className="text-xs font-extrabold text-brand">{c.dl}</span>
                <div className="num font-extrabold">{c.price}</div>
              </div>
              <Button size="sm">담기</Button>
            </div>
          </Card>
        ))}
      </div>

      {/* 임박 + 추천 */}
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <Section title="냉장고 임박" more="전체 ›" onMore={() => nav('/fridge')} />
          <Card className="px-4">
            {d.expiring.map((e, i) => (
              <div
                key={e.name}
                className={`flex items-center gap-3 py-3 ${i > 0 ? 'border-t border-line/60' : ''}`}
              >
                <Thumb>{e.emoji}</Thumb>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-bold">{e.name}</div>
                  <div className="text-xs text-sub">{e.sub}</div>
                </div>
                <Chip tone={e.tone}>{e.dday}</Chip>
              </div>
            ))}
          </Card>
        </div>
        <div>
          <Section title="오늘의 추천" more="더보기 ›" onMore={() => nav('/meal')} />
          <Card className="px-4">
            {d.recommend.map((r, i) => (
              <div
                key={r.name}
                className={`flex items-center gap-3 py-3 ${i > 0 ? 'border-t border-line/60' : ''}`}
              >
                <Thumb>{r.emoji}</Thumb>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-bold">{r.name}</div>
                  <div className="text-xs text-sub">{r.sub}</div>
                </div>
                <Button size="sm" variant="ghost">
                  보기
                </Button>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </div>
  )
}
