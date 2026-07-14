import { useNavigate } from 'react-router-dom'
import { ChevronLeft, X } from 'lucide-react'
import { cart as c } from '../lib/mock'
import { Card, Chip, Thumb, Bar, Button } from '../components/ui'

export default function Cart() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-5xl px-4 py-4 md:px-7 md:py-6">
      <button onClick={() => nav(-1)} className="mb-3 flex items-center gap-1 text-sm font-semibold text-sub">
        <ChevronLeft size={18} /> 뒤로
      </button>
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">장바구니</h1>
      <p className="mt-1 text-sm text-sub">보유 재고는 자동으로 빠졌어요. 예산 대비 비용을 확인하고 장보기를 확정하세요.</p>
      <div className="mt-5 grid gap-4 md:grid-cols-[1fr_340px] md:items-start">
        <Card>
          {c.items.map((it, i) => (
            <div key={i} className={`flex items-center gap-3 px-4 py-3 ${i > 0 ? 'border-t border-line/60' : ''}`}>
              <Thumb>{it.emoji}</Thumb>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-bold">{it.name}</div>
                <div className="text-xs text-sub">
                  {it.recipe} · {it.store}
                </div>
              </div>
              <span className="num text-sm font-extrabold">{it.price}</span>
              <button className="text-faint hover:text-sub">
                <X size={16} />
              </button>
            </div>
          ))}
          <div className="m-3 rounded-xl border border-dashed border-brand bg-brand-weak/30 p-3 text-xs text-brand">
            💡 <b>지금 싼 재료</b> — 애호박이 평균 대비 -22%예요.{' '}
            <button className="font-bold underline">₩1,290 담기</button>
          </div>
        </Card>
        <Card className="p-5 md:sticky md:top-20">
          <div className="flex justify-between text-[13px] text-sub">
            <span>장바구니 합계</span>
            <span className="num font-extrabold text-ink">₩{c.total}</span>
          </div>
          <div className="mt-2.5 flex justify-between text-[13px] text-sub">
            <span>이번 달 남은 예산</span>
            <span className="num font-extrabold text-ink">₩{c.remaining}</span>
          </div>
          <div className="my-4">
            <Bar value={c.percent} />
          </div>
          <div className="mb-4">
            <Chip tone="brand">예산 내 ✓ 담아도 ₩{c.after} 남아요</Chip>
          </div>
          <Button size="lg" className="w-full">
            장보기 완료 · 영수증 등록
          </Button>
          <Button variant="line" className="mt-2.5 w-full">
            목록만 저장
          </Button>
        </Card>
      </div>
    </div>
  )
}
