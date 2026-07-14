import { useNavigate } from 'react-router-dom'
import { hotdeal } from '../lib/mock'
import { won, storeName } from '../lib/format'
import { Card, Chip, Thumb, Button, Section } from '../components/ui'
import type { DealVM } from '../lib/types'

function DealCard({ d, onRecipe }: { d: DealVM; onRecipe: (id: number) => void }) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-3">
        <Thumb>{d.emoji}</Thumb>
        <div className="min-w-0">
          <div className="truncate font-bold">{d.name}</div>
          <div className="mt-0.5 text-xs text-sub">
            <Chip>{storeName(d.source)}</Chip>{' '}
            {d.unit_price
              ? `${won(d.unit_price)}/${d.unit_basis}`
              : d.discount_rate
                ? `${d.discount_rate}% 할인`
                : ''}
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-end justify-between">
        <div>
          {d.original_price && (
            <div className="num text-xs text-faint line-through">{won(d.original_price)}</div>
          )}
          <div className="num font-extrabold">{won(d.price)}</div>
        </div>
        {d.recipe_hint ? (
          <Button variant="ghost" size="sm" onClick={() => onRecipe(d.recipe_hint!.id)}>
            {d.recipe_hint.label}
          </Button>
        ) : (
          <Button size="sm">담기</Button>
        )}
      </div>
    </Card>
  )
}

export default function Hotdeal() {
  const nav = useNavigate()
  const onRecipe = (id: number) => nav('/recipes/' + id)
  const close = hotdeal.deals.filter((d) => d.deal_type === 'closeSale')
  const general = hotdeal.deals.filter((d) => d.deal_type === 'general')

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">핫딜</h1>
      <p className="mt-1 text-sm text-sub">
        오아시스 마감세일과 상시 특가를 모아 관련 레시피로 연결해요.{' '}
        <span className="text-faint">타임세일(15시)은 수집 예정 · 지금 싼 재료는 홈·장바구니에서.</span>
      </p>

      <Section title="🔥 마감세일" more="오아시스 · 오늘 마감" />
      <div className="grid gap-3 md:grid-cols-3">
        {close.map((d) => (
          <DealCard key={d.retail_product_id} d={d} onRecipe={onRecipe} />
        ))}
      </div>

      <Section title="💸 상시 특가" more="마켓컬리 할인" />
      <div className="grid gap-3 md:grid-cols-3">
        {general.map((d) => (
          <DealCard key={d.retail_product_id} d={d} onRecipe={onRecipe} />
        ))}
      </div>
    </div>
  )
}
