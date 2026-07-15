import { useMemo, useState } from 'react'
import Modal from './Modal'
import { won, type Ingredient } from '../lib/api'

type Src = 'kurly' | 'oasis'
const LABEL: Record<Src, string> = { kurly: '컬리', oasis: '오아시스' }

const priceOf = (g: Ingredient, s: Src): number | null =>
  s === 'kurly' ? g.kurly_krw_per_100g ?? null : g.oasis_krw_per_100g ?? null

const cheaperOf = (g: Ingredient): Src => {
  const k = g.kurly_krw_per_100g, o = g.oasis_krw_per_100g
  return k != null && (o == null || k <= o) ? 'kurly' : 'oasis'
}
// 요청 소스에 가격이 없으면 취급하는 쪽으로 대체
const effective = (g: Ingredient, want: Src): Src => (priceOf(g, want) != null ? want : want === 'kurly' ? 'oasis' : 'kurly')

// 담기 시점 구매처 선택 모달 — 재료별 컬리/오아시스 비교 후 최저가 기본선택.
export default function AddToCartModal({ open, onClose, recipeName, ingredients, onConfirm }: {
  open: boolean; onClose: () => void; recipeName: string; ingredients: Ingredient[]; onConfirm: () => void
}) {
  const buyable = useMemo(
    () => ingredients.filter((g) => g.kurly_krw_per_100g != null || g.oasis_krw_per_100g != null),
    [ingredients],
  )
  // 오버라이드만 저장 — 기본은 항상 최저가(cheaperOf)
  const [override, setOverride] = useState<Record<number, Src>>({})
  const keyOf = (g: Ingredient, i: number) => g.seq ?? i

  const chosen = (g: Ingredient, i: number): Src => effective(g, override[keyOf(g, i)] ?? cheaperOf(g))
  const total = buyable.reduce((a, g, i) => a + (priceOf(g, chosen(g, i)) ?? 0), 0)
  const storeTotal = (s: Src) => buyable.reduce((a, g) => a + (priceOf(g, effective(g, s)) ?? 0), 0)
  const lowestTotal = buyable.reduce((a, g) => a + (priceOf(g, cheaperOf(g)) ?? 0), 0)

  const setAll = (s: Src | 'lowest') => {
    if (s === 'lowest') return setOverride({})
    const next: Record<number, Src> = {}
    buyable.forEach((g, i) => (next[keyOf(g, i)] = s))
    setOverride(next)
  }

  const quick: [string, Src | 'lowest', number][] = [
    ['품목별 최저가', 'lowest', lowestTotal],
    ['전부 오아시스', 'oasis', storeTotal('oasis')],
    ['전부 컬리', 'kurly', storeTotal('kurly')],
  ]

  return (
    <Modal open={open} onClose={onClose} title="구매처 선택 · 장바구니 담기" maxWidth={560}>
      <div style={{ fontSize: 13, color: '#5E5E5E', marginBottom: 14 }}>
        <b style={{ color: '#17264A' }}>{recipeName}</b> 재료를 마켓별로 비교했어요. 품목마다 원하는 곳을 고르세요. <span style={{ color: '#9A9A9A' }}>(100g 기준가)</span>
      </div>

      {/* 일괄 선택 (매장 통합 합계) */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {quick.map(([label, s, t]) => (
          <button key={label} onClick={() => setAll(s)} style={{ flex: '1 1 150px', padding: '9px 10px', border: '1.5px solid #E6E6E6', background: '#fff', cursor: 'pointer', textAlign: 'left' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#17264A' }}>{label}</div>
            <div className="num" style={{ fontSize: 13.5, fontWeight: 800, color: '#F26419', marginTop: 2 }}>{won(t)}원</div>
          </button>
        ))}
      </div>
      <div style={{ fontSize: 11.5, color: '#9A9A9A', marginBottom: 6, marginTop: -6 }}>섞어 담으면 최저가지만, 한 곳으로 모으면 배송비가 한 번만 나와요.</div>

      {/* 재료별 토글 */}
      <div style={{ border: '1px solid #E6E6E6', marginTop: 12 }}>
        {buyable.map((g, i) => {
          const cur = chosen(g, i)
          return (
            <div key={keyOf(g, i)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 13px', borderTop: i ? '1px solid #EFEFEF' : 'none', flexWrap: 'wrap' }}>
              <div style={{ minWidth: 96, flex: 1 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, color: '#17264A' }}>{g.ingredient_name}</div>
                {g.quantity && <div style={{ fontSize: 11, color: '#9A9A9A' }}>{g.quantity}</div>}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {(['oasis', 'kurly'] as Src[]).map((s) => {
                  const p = priceOf(g, s)
                  const active = cur === s
                  const isCheapest = p != null && cheaperOf(g) === s && priceOf(g, 'kurly') != null && priceOf(g, 'oasis') != null
                  if (p == null)
                    return <div key={s} style={{ padding: '7px 11px', fontSize: 11.5, border: '1px solid #EFEFEF', background: '#FAFAFA', color: '#C4C4C4', minWidth: 78, textAlign: 'center' }}>{LABEL[s]}<br />미취급</div>
                  return (
                    <button key={s} onClick={() => setOverride((o) => ({ ...o, [keyOf(g, i)]: s }))}
                      style={{ padding: '7px 11px', minWidth: 78, border: active ? '1.5px solid #F26419' : '1.5px solid #E6E6E6', background: active ? '#FCEBDD' : '#fff', color: active ? '#F26419' : '#5E5E5E', cursor: 'pointer', textAlign: 'center', position: 'relative' }}>
                      <div style={{ fontSize: 11, fontWeight: 600 }}>{LABEL[s]}{isCheapest && <span style={{ color: '#15B76E' }}> ↓</span>}</div>
                      <div className="num" style={{ fontSize: 12.5, fontWeight: 800 }}>{won(p)}</div>
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>

      {/* 합계 + 담기 */}
      <div style={{ marginTop: 16, padding: '14px 16px', background: '#FCEBDD', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 12, color: '#F26419' }}>선택 합계 · 100g 기준 {buyable.length}개</div>
          <div className="num" style={{ fontSize: 20, fontWeight: 800, color: '#F26419' }}>{won(total)}원</div>
        </div>
        <button onClick={onConfirm} style={{ padding: '12px 20px', border: 'none', background: '#F26419', color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>{buyable.length}개 장바구니 담기</button>
      </div>
    </Modal>
  )
}
