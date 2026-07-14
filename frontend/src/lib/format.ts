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
  s === 'kurly' ? '마켓컬리' : s === 'oasis' ? '오아시스' : s

// retail_item_price_compare 행 → 더 싼 소스/가격
export const cheaper = (
  kurly: number | null,
  oasis: number | null,
): { source: RetailSource; price: number } | null => {
  if (kurly != null && (oasis == null || kurly <= oasis)) return { source: 'kurly', price: kurly }
  if (oasis != null) return { source: 'oasis', price: oasis }
  return null
}
