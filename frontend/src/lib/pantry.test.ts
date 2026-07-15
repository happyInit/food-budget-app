// 순수 매핑/파생 로직 테스트 (vitest). 백엔드행 → 냉장고 표시 VM, D-day·긴급도·폼→요청.
// 리터럴로 검증(독립 소스). 컴포넌트/네트워크 없음 — 순수 함수만.
import { describe, it, expect } from 'vitest'
import type { PantryItemRow } from './types'
import {
  storageToZone,
  zoneToStorage,
  daysLeft,
  ddayLabel,
  urgency,
  qtyLabel,
  toDisplay,
  formToRequest,
  photoIndex,
} from './pantry'

const TODAY = new Date(2026, 6, 15) // 2026-07-15 (month 0-indexed)

describe('storage ↔ zone', () => {
  it('maps both ways', () => {
    expect(storageToZone('FRIDGE')).toBe('fridge')
    expect(zoneToStorage('freezer')).toBe('FREEZER')
  })
})

describe('daysLeft', () => {
  it('counts date-only days (null passthrough)', () => {
    expect(daysLeft('2026-07-16', TODAY)).toBe(1)
    expect(daysLeft('2026-07-15', TODAY)).toBe(0)
    expect(daysLeft('2026-07-10', TODAY)).toBe(-5)
    expect(daysLeft(null, TODAY)).toBe(null)
  })
})

describe('ddayLabel', () => {
  it('D-1 for tomorrow', () => expect(ddayLabel('2026-07-16', 'FRIDGE', TODAY)).toBe('D-1'))
  it('만료 for past', () => expect(ddayLabel('2026-07-14', 'FRIDGE', TODAY)).toBe('만료'))
  it('D-30+ beyond a month', () => expect(ddayLabel('2026-09-01', 'ROOM', TODAY)).toBe('D-30+'))
  it('냉동 for freezer w/o expiry', () => expect(ddayLabel(null, 'FREEZER', TODAY)).toBe('냉동'))
  it('- for room/fridge w/o expiry', () => expect(ddayLabel(null, 'ROOM', TODAY)).toBe('-'))
})

describe('urgency', () => {
  it('tiers by days left', () => {
    expect(urgency(1)).toBe('danger')
    expect(urgency(5)).toBe('warn')
    expect(urgency(12)).toBe('ok')
    expect(urgency(null)).toBe('ok')
  })
})

describe('qtyLabel', () => {
  it('combines quantity + storage label', () => {
    expect(qtyLabel('1모', 'FRIDGE')).toBe('1모 · 냉장')
    expect(qtyLabel(null, 'ROOM')).toBe('실온')
  })
})

describe('toDisplay', () => {
  it('maps a server row to the fridge card VM', () => {
    const row: PantryItemRow = {
      id: 5, item_id: 100, name: '두부', quantity: '1모', storage: 'FRIDGE',
      expire_at: '2026-07-16', source: 'MANUAL', status: 'ACTIVE',
      created_at: '2026-07-15T00:00:00Z', closed_at: null,
    }
    const vm = toDisplay(row, TODAY)
    expect(vm).toMatchObject({
      id: 5, name: '두부', qty: '1모 · 냉장', dday: 'D-1', urg: 'danger', zone: 'fridge',
    })
    expect(vm.p).toBe(photoIndex(5))          // 사진 인덱스는 id에서 결정적으로
    expect(vm.fresh).toBeGreaterThan(0)        // 신선도 바(플레이스홀더) 0~100
  })
})

describe('formToRequest', () => {
  it('combines qty+unit, maps storage, omits empty expire', () => {
    expect(formToRequest({ name: '대파', qty: '2', unit: '단', expire: '', storage: 'FRIDGE' }))
      .toEqual({ name: '대파', storage: 'FRIDGE', quantity: '2단' })
  })
  it('includes expire_at when provided', () => {
    expect(formToRequest({ name: '우유', qty: '1', unit: 'L', expire: '2026-07-20', storage: 'FRIDGE' }))
      .toEqual({ name: '우유', storage: 'FRIDGE', quantity: '1L', expire_at: '2026-07-20' })
  })
})
