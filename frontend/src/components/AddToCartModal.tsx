import { useMemo, useState } from 'react'
import Modal from './Modal'
import { won, type Ingredient } from '../lib/api'
import { SRC_LABEL } from '../lib/format'
import { defaultChecked, ownedItemIds } from '../lib/cart'
import { usePantryItems } from '../lib/queries'

type Src = 'kurly' | 'oasis'

// 담기 확정 시 부모로 넘기는 선택 결과 (item_id·수량·선호 소스)
export type CartPick = { name: string; item_id: number | null; quantity: string | null; source: Src }

const priceOf = (g: Ingredient, s: Src): number | null =>
  s === 'kurly' ? g.kurly_krw_per_100g ?? null : g.oasis_krw_per_100g ?? null

const cheaperOf = (g: Ingredient): Src => {
  const k = g.kurly_krw_per_100g, o = g.oasis_krw_per_100g
  return k != null && (o == null || k <= o) ? 'kurly' : 'oasis'
}
// 요청 소스에 가격이 없으면 취급하는 쪽으로 대체
const effective = (g: Ingredient, want: Src): Src => (priceOf(g, want) != null ? want : want === 'kurly' ? 'oasis' : 'kurly')

// 담기 시점 구매처 선택 모달 — 재료별 컬리/오아시스 비교 후 최저가 기본선택.
// #614 냉장고 보유 재료는 **목록에서 빼지 않고** 배지 + 체크 해제로 둔다 — quantity 가 '2대' 같은
// 표시용 문자열이라 수량 차감이 불가능해서, 한 뿌리 남았는데 4대 필요한 경우를 유저가 되살릴 수 있어야 한다.
export default function AddToCartModal({ open, onClose, recipeName, ingredients, onConfirm, pending }: {
  open: boolean; onClose: () => void; recipeName: string; ingredients: Ingredient[]
  onConfirm: (picks: CartPick[]) => void; pending?: boolean
}) {
  const buyable = useMemo(
    () => ingredients.filter((g) => g.kurly_krw_per_100g != null || g.oasis_krw_per_100g != null),
    [ingredients],
  )
  // 냉장고 재고 — 모달이 열렸을 때만 조회. 실패·미배선이면 data 가 undefined → 보유 0건으로
  // 전부 체크된 채 그대로 담긴다(degrade — 재고를 못 읽는다고 담기가 막히면 안 된다).
  const { data: pantry, isPending: pantryPending } = usePantryItems(open)
  const ownedIds = useMemo(() => ownedItemIds(pantry), [pantry])
  // item_id 미매칭 재료는 보유 판정이 불가능 → 보유 아님(= 체크 유지)으로 본다(lib/cart).
  const owned = (g: Ingredient) => !defaultChecked(g.item_id, ownedIds)

  // 오버라이드만 저장 — 기본은 항상 최저가(cheaperOf)
  const [override, setOverride] = useState<Record<number, Src>>({})
  // 체크도 오버라이드만 저장 — 기본은 '보유하지 않은 것만 체크'. 재고가 늦게 도착해도(비동기)
  // 유저가 직접 건드린 행은 그대로 두고 나머지 기본값만 갱신된다.
  const [checkOverride, setCheckOverride] = useState<Record<number, boolean>>({})
  const keyOf = (g: Ingredient, i: number) => g.seq ?? i

  const chosen = (g: Ingredient, i: number): Src => effective(g, override[keyOf(g, i)] ?? cheaperOf(g))
  const checked = (g: Ingredient, i: number): boolean => checkOverride[keyOf(g, i)] ?? !owned(g)
  // 합계는 전부 **체크된 것만** 센다 — 안 그러면 "합계 12,000원"인데 8,000원어치만 담긴다.
  const sumOf = (src: (g: Ingredient, i: number) => Src) =>
    buyable.reduce((a, g, i) => a + (checked(g, i) ? priceOf(g, src(g, i)) ?? 0 : 0), 0)
  const total = sumOf(chosen)
  const storeTotal = (s: Src) => sumOf((g) => effective(g, s))
  const lowestTotal = sumOf(cheaperOf)
  const pickedCount = buyable.filter((g, i) => checked(g, i)).length
  const ownedCount = buyable.filter((g) => owned(g)).length

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

  const confirm = () => {
    const picks: CartPick[] = buyable
      .map((g, i) => ({ g, i }))
      .filter(({ g, i }) => checked(g, i))          // #614 체크된 것만 담는다
      .map(({ g, i }) => ({
        name: g.ingredient_name ?? '재료',
        item_id: g.item_id ?? null,
        quantity: g.quantity ?? null,
        source: chosen(g, i),
      }))
    onConfirm(picks)
  }

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

      {/* #614 냉장고에 있는 재료는 기본 해제 — 왜 빠졌는지 화면에서 보이게 한 줄 안내.
          아직 재고를 못 읽은 동안에도 담기를 막지 않는다(안내만) — 재고 조회 실패가 담기를
          막으면 안 된다는 게 degrade 요구사항이라, 버튼을 잠그는 대신 상태만 알린다. */}
      {pantryPending ? (
        <div style={{ fontSize: 12, color: '#9A9A9A', marginTop: 10 }}>냉장고 재고 확인 중…</div>
      ) : ownedCount > 0 && (
        <div style={{ fontSize: 12, color: '#15B76E', marginTop: 10, fontWeight: 600 }}>
          냉장고에 있는 {ownedCount}개는 빼뒀어요. 더 필요하면 체크해서 같이 담을 수 있어요.
        </div>
      )}

      {/* 재료별 토글 */}
      <div style={{ border: '1px solid #E6E6E6', marginTop: 12 }}>
        {buyable.map((g, i) => {
          const cur = chosen(g, i)
          const on = checked(g, i)
          const has = owned(g)
          return (
            <div key={keyOf(g, i)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 13px', borderTop: i ? '1px solid #EFEFEF' : 'none', flexWrap: 'wrap' }}>
              <input
                type="checkbox"
                checked={on}
                onChange={(e) => setCheckOverride((c) => ({ ...c, [keyOf(g, i)]: e.target.checked }))}
                aria-label={`${g.ingredient_name ?? '재료'} 담기`}
                style={{ width: 17, height: 17, accentColor: '#F26419', cursor: 'pointer', flexShrink: 0 }}
              />
              <div style={{ minWidth: 96, flex: 1, opacity: on ? 1 : 0.55 }}>
                <div style={{ fontSize: 13.5, fontWeight: 600, color: '#17264A', display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  {g.ingredient_name}
                  {has && <span style={{ fontSize: 10.5, fontWeight: 700, color: '#15B76E', background: '#F1FBF5', border: '1px solid #C9EBD8', padding: '2px 6px' }}>냉장고에 있음</span>}
                </div>
                {g.quantity && <div style={{ fontSize: 11, color: '#9A9A9A' }}>{g.quantity}</div>}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {(['oasis', 'kurly'] as Src[]).map((s) => {
                  const p = priceOf(g, s)
                  const active = cur === s
                  const isCheapest = p != null && cheaperOf(g) === s && priceOf(g, 'kurly') != null && priceOf(g, 'oasis') != null
                  if (p == null)
                    return <div key={s} style={{ padding: '7px 11px', fontSize: 11.5, border: '1px solid #EFEFEF', background: '#FAFAFA', color: '#C4C4C4', minWidth: 78, textAlign: 'center' }}>{SRC_LABEL[s]}<br />미취급</div>
                  return (
                    <button key={s} onClick={() => setOverride((o) => ({ ...o, [keyOf(g, i)]: s }))}
                      style={{ padding: '7px 11px', minWidth: 78, border: active ? '1.5px solid #F26419' : '1.5px solid #E6E6E6', background: active ? '#FCEBDD' : '#fff', color: active ? '#F26419' : '#5E5E5E', cursor: 'pointer', textAlign: 'center', position: 'relative' }}>
                      <div style={{ fontSize: 11, fontWeight: 600 }}>{SRC_LABEL[s]}{isCheapest && <span style={{ color: '#15B76E' }}> ↓</span>}</div>
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
          <div style={{ fontSize: 12, color: '#F26419' }}>선택 합계 · 100g 기준 {pickedCount}개</div>
          <div className="num" style={{ fontSize: 20, fontWeight: 800, color: '#F26419' }}>{won(total)}원</div>
        </div>
        <button onClick={confirm} disabled={pending || pickedCount === 0} style={{ padding: '12px 20px', border: 'none', background: pending || pickedCount === 0 ? '#E6B48F' : '#F26419', color: '#fff', fontSize: 14, fontWeight: 700, cursor: pending || pickedCount === 0 ? 'not-allowed' : 'pointer' }}>{pending ? '담는 중…' : `${pickedCount}개 장바구니 담기`}</button>
      </div>
    </Modal>
  )
}
