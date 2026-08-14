// 담기 선택 로직 테스트(#614, vitest) — 컴포넌트/네트워크 없이 순수 함수만.
import { describe, it, expect } from 'vitest'
import type { ItemStatus, PantryItemRow } from './types'
import { defaultChecked, ownedItemIds } from './cart'

const row = (id: number, item_id: number | null, status: ItemStatus = 'ACTIVE'): PantryItemRow => ({
  id,
  item_id,
  name: '대파',
  quantity: '1단',
  storage: 'FRIDGE',
  expire_at: null,
  source: 'MANUAL',
  status,
  created_at: '2026-08-13T00:00:00Z',
  closed_at: null,
})

describe('ownedItemIds', () => {
  it('keeps ACTIVE item_id-anchored stock only', () => {
    const owned = ownedItemIds([
      row(1, 10),                    // 대파 — 보유
      row(2, 20, 'CONSUMED'),        // 먹음 → 보유 아님
      row(3, 30, 'DISCARDED'),       // 버림 → 보유 아님
      row(4, null),                  // 품목 미매칭 → 판정 불가
    ])
    expect(owned).toEqual(new Set([10]))
  })

  it('degrades to empty when pantry is missing (조회 실패·미도착)', () => {
    expect(ownedItemIds(undefined)).toEqual(new Set())
    expect(ownedItemIds(null)).toEqual(new Set())
    expect(ownedItemIds([])).toEqual(new Set())
  })
})

describe('defaultChecked', () => {
  const owned = ownedItemIds([row(1, 10)])

  it('unchecks what the fridge already has', () => {
    expect(defaultChecked(10, owned)).toBe(false)
  })

  it('checks what the fridge lacks', () => {
    expect(defaultChecked(99, owned)).toBe(true)
  })

  it('always checks unmatched ingredients (item_id null) — 판정 불가는 빼지 않는다', () => {
    expect(defaultChecked(null, owned)).toBe(true)
    expect(defaultChecked(undefined, owned)).toBe(true)
  })

  it('checks everything when the fridge is empty or unavailable', () => {
    const none = ownedItemIds(undefined)
    expect(defaultChecked(10, none)).toBe(true)
  })
})
