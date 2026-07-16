// DB는 가격을 numeric(원)으로 준다 → 표시 시점에 포맷. 저장/전송은 항상 숫자.
import type { RetailSource } from './types'

export const won = (n: number | null | undefined): string =>
  n == null ? '-' : '₩' + Math.round(n).toLocaleString('ko-KR')

// 원 단위 → '₩4.6만' 축약 (큰 금액 카드용)
export const wonShort = (n: number | null | undefined): string => {
  if (n == null) return '-'
  if (n >= 10000) return '₩' + (n / 10000).toFixed(n % 10000 ? 1 : 0) + '만'
  return won(n)
}

export const storeName = (s: RetailSource): string =>
  s === 'kurly' ? '마켓컬리' : s === 'oasis' ? '오아시스마켓' : s

// 가격 출처 공통 안내 문구 — "마켓컬리·오아시스마켓 중 최저가" 기준임을 명시.
export const PRICE_BASIS = '마켓컬리·오아시스마켓 최저가'

// 마켓 소스 짧은 라벨(컬리/오아시스) — 칩·인라인 표기용. storeName 은 정식명(마켓컬리).
// 미지의 소스는 호출측에서 `SRC_LABEL[s] ?? s` 로 원문 폴백. Cart·RecipeDetail·AddToCartModal·Hotdeal 공용.
export const SRC_LABEL: Record<string, string> = { kurly: '컬리', oasis: '오아시스' }

// retail_item_price_compare 행 → 더 싼 소스/가격
export const cheaper = (
  kurly: number | null,
  oasis: number | null,
): { source: RetailSource; price: number } | null => {
  if (kurly != null && (oasis == null || kurly <= oasis)) return { source: 'kurly', price: kurly }
  if (oasis != null) return { source: 'oasis', price: oasis }
  return null
}
