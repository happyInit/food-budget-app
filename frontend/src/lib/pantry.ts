// 냉장고(pantry) 순수 매핑/파생 로직 — React·네트워크 무관(vitest로 test-first).
// 백엔드는 원시 행(PantryItemRow)만 주고, D-day·긴급도·표시수량은 프론트가 계산(CONVENTIONS §1).
import type { PantryAddBody, PantryItemRow, Storage } from './types'

export type ZoneKey = 'room' | 'fridge' | 'freezer'

const S2Z: Record<Storage, ZoneKey> = { ROOM: 'room', FRIDGE: 'fridge', FREEZER: 'freezer' }
const Z2S: Record<ZoneKey, Storage> = { room: 'ROOM', fridge: 'FRIDGE', freezer: 'FREEZER' }
const STORAGE_LABEL: Record<Storage, string> = { ROOM: '실온', FRIDGE: '냉장', FREEZER: '냉동' }

export const storageToZone = (s: Storage): ZoneKey => S2Z[s]
export const zoneToStorage = (z: ZoneKey): Storage => Z2S[z]
export const storageLabel = (s: Storage): string => STORAGE_LABEL[s]

// 남은 일수(date-only 차이, 시각 무시). expire_at 없으면 null.
export function daysLeft(expireAt: string | null, today: Date): number | null {
  if (!expireAt) return null
  const exp = new Date(expireAt + 'T00:00:00')
  const base = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  return Math.round((exp.getTime() - base.getTime()) / 86_400_000)
}

// D-day 라벨(프론트 파생). 만료·30일+·냉동 무기한 등.
export function ddayLabel(expireAt: string | null, storage: Storage, today: Date): string {
  const d = daysLeft(expireAt, today)
  if (d === null) return storage === 'FREEZER' ? '냉동' : '-'
  if (d < 0) return '만료'
  if (d > 30) return 'D-30+'
  return `D-${d}`
}

// 긴급도 tier(색상). null(무기한)=ok. 임박 D-2 이하=danger, D-6 이하=warn.
export function urgency(d: number | null): 'danger' | 'warn' | 'ok' {
  if (d === null) return 'ok'
  if (d <= 2) return 'danger'
  if (d <= 6) return 'warn'
  return 'ok'
}

// 신선도 바(0~100) — ⚠️ 플레이스홀더. 실제 신선도 예측은 P1 AI(XGBoost), 아직 백엔드 미제공.
// 지금은 만료 근접도(남은일수/30)를 대용으로 표시.
export function freshnessProxy(d: number | null): number {
  if (d === null) return 100
  return Math.max(5, Math.min(100, Math.round((d / 30) * 100)))
}

// 사진 인덱스 — 백엔드에 이미지 없음 → id 에서 결정적으로 파생(플레이스홀더, data.ts img() 사용).
export const photoIndex = (id: number): number => ((id % 15) + 15) % 15

// 수량 표시 "1모 · 냉장" (수량 없으면 보관 라벨만).
export function qtyLabel(quantity: string | null, storage: Storage): string {
  const label = storageLabel(storage)
  return quantity ? `${quantity} · ${label}` : label
}

export type PantryVM = {
  id: number
  name: string
  qty: string
  dday: string
  urg: 'danger' | 'warn' | 'ok'
  fresh: number
  p: number
  zone: ZoneKey
}

// 서버 행 → 냉장고 카드 표시 VM.
export function toDisplay(row: PantryItemRow, today: Date): PantryVM {
  const d = daysLeft(row.expire_at, today)
  return {
    id: row.id,
    name: row.name,
    qty: qtyLabel(row.quantity, row.storage),
    dday: ddayLabel(row.expire_at, row.storage, today),
    urg: urgency(d),
    fresh: freshnessProxy(d),
    p: photoIndex(row.id),
    zone: storageToZone(row.storage),
  }
}

// 직접등록 폼 → POST /api/pantry/items 요청 바디(PantryAddBody).
export type AddForm = { name: string; qty: string; unit: string; expire: string; storage: Storage }

export function formToRequest(f: AddForm): PantryAddBody {
  const quantity = [f.qty.trim(), f.unit.trim()].filter(Boolean).join('')
  const body: PantryAddBody = { name: f.name.trim(), storage: f.storage }
  if (quantity) body.quantity = quantity
  if (f.expire.trim()) body.expire_at = f.expire.trim()
  return body
}
