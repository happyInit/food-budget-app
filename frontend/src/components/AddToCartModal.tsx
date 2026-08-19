import { useMemo, useState } from 'react'
import Modal from './Modal'
import { won, type Ingredient } from '../lib/api'
import { SRC_LABEL } from '../lib/format'
import { defaultChecked, ownedItemIds } from '../lib/cart'
import { usePantryItems } from '../lib/queries'

type Src = 'kurly' | 'oasis'

// 담기 확정 시 부모로 넘기는 선택 결과 (item_id·수량·선호 소스)
export type CartPick = { name: string; item_id: number | null; quantity: string | null; source: Src }

// 🔴 **상비재료(양념·유지·액체)는 가격을 매기지 않는다.** 서버가 이미 그렇게 판정해서 보낸다 —
//    `services/recipe/app/queries.py`: `is_liquid_excl(name) or category in ('양념','유지')`
//    → `cost_basis = 'excluded_staple'`. 레시피 상세(`IngredientPanels`)는 그 값을 보고 `-` 를
//    찍는데, **이 모달만 그걸 무시하고 100g 단가를 그대로 보여주고 있었다**(2026-08-19 발견).
//
// 🔴 그 대가가 컸다 — 돼지갈비 레시피의 «선택 합계 24,358원» 중 **21,761원(89%)이 양념**이었고,
//    정작 고기는 1,189원(4.9%)이었다. «후추 약간» 이 8,880원으로 고기보다 7배 비쌌다.
//
// 🔴 그리고 그 숫자들은 **틀린 상품**에서 왔다. 양념·유지 34건 중 18건(53%)이 오매칭이다:
//      참기름 → `[동원] 양반 참기름 식탁김`(김 스낵)
//      설탕   → `[저당미식] 설탕을 넣지 않은 제육볶음 500g (냉동)`   ← 부정어를 못 읽는다
//      간장   → `춘천 닭갈비의 정석 간장맛(500g)`
//    ⇒ 상비를 빼면 **그 오류가 화면에서 통째로 사라진다.** 매칭 수정은 별건(파이프라인)이다.
// ⚠️ 상비 판정 신호가 **경로마다 다르다** — 하나만 보면 절반이 조용히 새 나간다:
//      만개 레시피(RecipeDetail)      → `cost_basis = 'excluded_staple' | 'excluded_liquid'`
//      유저·공유 레시피(recipebook)   → `excluded = true`  (#451 read-time 정책)
//    둘 다 «상비양념은 재료비에서 뺀다» 는 같은 결정의 표현이라 여기서 합친다.
const isStaple = (g: Ingredient): boolean =>
  g.excluded === true ||
  g.cost_basis === 'excluded_staple' || g.cost_basis === 'excluded_liquid'

const priceOf = (g: Ingredient, s: Src): number | null =>
  // 🔵 상비재료는 «가격 없음» 으로 취급한다 — 그래야 합계·최저가·미취급 판정이 전부
  //    한 곳에서 일관되게 빠진다. 각 자리에 조건을 흩어 놓으면 하나를 빠뜨린다.
  isStaple(g) ? null : (s === 'kurly' ? g.kurly_krw_per_100g ?? null : g.oasis_krw_per_100g ?? null)

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
  // 🔵 상비재료도 **목록에는 남긴다** — 없는 사람이 «참기름이 왜 안 보이지» 로 헤매지 않게.
  //    가격만 안 매기고 배지로 이유를 말한다(레시피 상세의 `-` 표시와 같은 규칙).
  const buyable = useMemo(
    () => ingredients.filter(
      (g) => isStaple(g) || g.kurly_krw_per_100g != null || g.oasis_krw_per_100g != null),
    [ingredients],
  )
  const stapleCount = useMemo(() => buyable.filter(isStaple).length, [buyable])
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
  // 🔴 상비재료는 기본 해제다 — 집에 있는 게 전제라서고, 가격도 안 매기므로 담아도 합계가 0 이다.
  //    유저가 직접 체크하면 담긴다(장바구니 합계에서는 서버가 다시 뺀다 — `_cart_subtotal`).
  const checked = (g: Ingredient, i: number): boolean =>
    checkOverride[keyOf(g, i)] ?? (!owned(g) && !isStaple(g))
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
          {/* 🔵 «빼뒀어요» 는 목록에서 사라졌다는 뜻으로도 읽힌다 — 실제로는 **선택만** 풀었다.
              무슨 일이 일어났는지와 되살리는 법을 각각 한 문장으로 말한다. */}
          냉장고에 있는 {ownedCount}개는 선택을 풀어 뒀어요. 더 필요하면 체크해서 같이 담으세요.
        </div>
      )}
      {/* 🔵 왜 값이 «—» 인지 화면에서 말해 준다 — 안 그러면 «가격을 못 불러왔나» 로 읽힌다. */}
      {stapleCount > 0 && (
        <div style={{ fontSize: 12, color: '#8A6D3B', marginTop: 6, fontWeight: 600 }}>
          소금·간장 같은 상비양념 {stapleCount}개는 집에 있다고 보고 값을 매기지 않았어요.
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
                  {isStaple(g) && <span style={{ fontSize: 10.5, fontWeight: 700, color: '#8A6D3B', background: '#FDF6E3', border: '1px solid #EBDCB8', padding: '2px 6px' }}>상비양념</span>}
                </div>
                {g.quantity && <div style={{ fontSize: 11, color: '#9A9A9A' }}>{g.quantity}</div>}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {/* 🔴 상비재료는 «미취급» 이 아니다 — 파는데 우리가 값을 안 매기는 것이다.
                    같은 회색 칸으로 뭉뚱그리면 유저가 «컬리가 후추를 안 판다» 로 읽는다. */}
                {isStaple(g) ? (
                  <div style={{ padding: '7px 11px', fontSize: 11.5, border: '1px solid #EFEFEF', background: '#FAFAFA', color: '#9A9A9A', minWidth: 162, textAlign: 'center' }}>
                    상비양념<br /><span style={{ fontSize: 12.5, fontWeight: 700 }}>—</span>
                  </div>
                ) : (['oasis', 'kurly'] as Src[]).map((s) => {
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
