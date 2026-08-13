// 장바구니 담기 선택 로직(#614) — React·네트워크 무관 순수 함수(vitest로 검증).
// 냉장고 보유분을 **목록에서 빼지 않고** 기본 체크 해제로만 반영한다: `quantity`가 '2대' 같은
// 표시용 문자열이라 수량 차감이 불가능해서, 한 뿌리 남았는데 4대 필요한 경우를 유저가 되살릴 수
// 있어야 한다(제외했다면 되살릴 방법이 없다).
import type { PantryItemRow } from './types'

// 냉장고에서 "지금 갖고 있다"고 볼 수 있는 표준품목 id 집합.
//   * ACTIVE 만 — 먹었거나(CONSUMED) 버린(DISCARDED) 건 보유가 아니다.
//   * item_id 앵커된 것만 — 이름만으로 동일 품목이라 단정할 수 없다(재료 매칭 기준은 표준품목 id).
// pantry 미도착·조회 실패(undefined)면 빈 집합 → 아무것도 해제되지 않는다(degrade).
export function ownedItemIds(pantry: PantryItemRow[] | undefined | null): Set<number> {
  return new Set(
    (pantry ?? [])
      .filter((p) => p.status === 'ACTIVE' && p.item_id != null)
      .map((p) => p.item_id as number),
  )
}

// 담기 기본 체크 = 보유하지 않은 것만 체크. item_id 미매칭(null)은 보유 판정이 불가능하므로
// **항상 체크 유지** — 판정 못 하는 것을 조용히 빼면 유저가 사야 할 걸 못 산다.
export function defaultChecked(itemId: number | null | undefined, owned: Set<number>): boolean {
  return itemId == null || !owned.has(itemId)
}
