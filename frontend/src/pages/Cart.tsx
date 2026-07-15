import { useState } from 'react'
import Modal from '../components/Modal'
import OcrFlow from '../components/forms/OcrFlow'
import { won, type CartItemT } from '../lib/api'
import { useCart, useCheckout, useDeleteCartItem } from '../lib/queries'

const SRC_LABEL: Record<string, string> = { kurly: '컬리', oasis: '오아시스' }
// 라인 소계 = 100g 최저 단가 × 수량 (백엔드 subtotal 정의와 동일)
const lineTotal = (it: CartItemT) => (it.lowest_krw_per_100g == null ? null : it.lowest_krw_per_100g * it.qty)

export default function Cart() {
  const [ocr, setOcr] = useState(false)
  const { data, isLoading, error } = useCart()
  const del = useDeleteCartItem()
  const checkout = useCheckout()
  const [done, setDone] = useState<{ amount: number } | null>(null)

  const items = data?.items ?? []
  const subtotal = data?.subtotal ?? 0
  const hasBudget = data?.budget != null
  const priced = items.filter((it) => it.lowest_krw_per_100g != null).length

  const onCheckout = () => {
    checkout.mutate(undefined, {
      onSuccess: (r) => setDone({ amount: r.order.amount }),
    })
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>장바구니</h1>
        <span style={{ fontSize: 13, color: '#9A9A9A' }}>담은 재료 {items.length}개 · 100g 최저가 기준</span>
      </div>

      {isLoading && <div style={{ color: '#9A9A9A', padding: '40px 4px' }}>불러오는 중…</div>}
      {error && (
        <div style={{ padding: '30px 4px' }}>
          <div style={{ color: '#F04452', fontWeight: 700, marginBottom: 6 }}>장바구니를 불러오지 못했어요</div>
          <div style={{ color: '#9A9A9A', fontSize: 13 }}>{error.message}</div>
        </div>
      )}

      {!isLoading && !error && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 16 }}>
          {/* 좌: 상품 목록 */}
          <div style={{ background: '#fff', border: '1px solid #E6E6E6', padding: 20 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 6px' }}>담은 재료</h3>
            {items.length === 0 && (
              <div style={{ textAlign: 'center', padding: '40px 10px', color: '#9A9A9A', fontSize: 13.5 }}>
                장바구니가 비어 있어요.<br />레시피 상세에서 <b style={{ color: '#F26419' }}>장바구니 담기</b>로 재료를 추가해보세요.
              </div>
            )}
            {items.map((it) => {
              const lt = lineTotal(it)
              return (
                <div key={it.id} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '14px 0', borderTop: '1px solid #EFEFEF' }}>
                  <div style={{ width: 56, height: 56, background: '#FCEBDD', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#F26419', fontSize: 13, fontWeight: 800 }}>
                    ×{it.qty}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>{it.name}</div>
                    <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 2 }}>
                      {it.quantity ? `${it.quantity} · ` : ''}
                      {it.source ? <b style={{ color: '#F26419', fontWeight: 700 }}>{SRC_LABEL[it.source] ?? it.source} 최저가</b> : '가격 미확인'}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="num" style={{ fontSize: 15, fontWeight: 700, whiteSpace: 'nowrap', color: lt == null ? '#B5B5B5' : '#17264A' }}>
                      {lt == null ? '-' : `${won(lt)}원`}
                    </div>
                    {lt != null && <div style={{ fontSize: 10.5, color: '#9A9A9A' }}>100g×{it.qty}</div>}
                  </div>
                  <button
                    onClick={() => del.mutate(it.id)}
                    disabled={del.isPending}
                    aria-label="삭제"
                    style={{ width: 26, height: 26, border: '1px solid #E6E6E6', background: '#fff', color: '#9A9A9A', cursor: 'pointer', flexShrink: 0 }}
                  >
                    ✕
                  </button>
                </div>
              )
            })}
          </div>

          {/* 우: 예산·결제 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ background: '#F26419', color: '#fff', padding: 22 }}>
              <div style={{ fontSize: 13, opacity: 0.9 }}>{hasBudget ? '이번 달 예산 잔여' : '담은 재료 합계 (100g 기준)'}</div>
              <div className="num" style={{ fontSize: 27, fontWeight: 800, margin: '6px 0' }}>
                {hasBudget ? (
                  <>
                    {won(data!.remaining)}원 <span style={{ fontSize: 14, opacity: 0.75 }}>/ {won(data!.budget)}원</span>
                  </>
                ) : (
                  <>{won(subtotal)}원</>
                )}
              </div>
              {!hasBudget && <div style={{ fontSize: 11.5, opacity: 0.85 }}>예산 잔여는 계정 연동 후 표시돼요.</div>}
            </div>

            <div style={{ background: '#fff', border: '1px solid #E6E6E6', padding: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 8 }}>
                <span style={{ color: '#5E5E5E' }}>재료 합계 (가격 {priced}/{items.length})</span>
                <span className="num">{won(subtotal)}원</span>
              </div>
              <div style={{ height: 1, background: '#E6E6E6', margin: '12px 0' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, fontWeight: 700 }}>
                <span>예상 결제</span>
                <span className="num" style={{ color: '#F26419' }}>{won(subtotal)}원</span>
              </div>
              <div style={{ fontSize: 11, color: '#9A9A9A', marginTop: 8 }}>* 100g 최저 단가 × 수량 추정치예요.</div>
            </div>

            <button
              onClick={onCheckout}
              disabled={items.length === 0 || checkout.isPending}
              style={{ width: '100%', padding: 14, border: 'none', background: items.length === 0 ? '#E6E6E6' : '#F26419', color: '#fff', fontSize: 14, fontWeight: 700, cursor: items.length === 0 ? 'not-allowed' : 'pointer' }}
            >
              {checkout.isPending ? '기록 중…' : '구매 완료 · 지출로 기록'}
            </button>
            <button onClick={() => setOcr(true)} style={{ width: '100%', padding: 12, border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>영수증으로 재고 등록</button>
          </div>
        </div>
      )}

      {/* 결제 완료 안내 */}
      <Modal open={done != null} onClose={() => setDone(null)} title="구매 완료">
        <div style={{ padding: '4px 2px 8px' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#17264A', marginBottom: 8 }}>지출로 기록했어요 🧾</div>
          <div style={{ fontSize: 13.5, color: '#5E5E5E', lineHeight: 1.6 }}>
            <b className="num" style={{ color: '#F26419' }}>{won(done?.amount)}원</b>이 이번 달 식비(집밥)로 기록되고, 장바구니는 비워졌어요.
          </div>
          <button onClick={() => setDone(null)} style={{ marginTop: 16, width: '100%', padding: 12, border: 'none', background: '#F26419', color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>확인</button>
        </div>
      </Modal>

      <Modal open={ocr} onClose={() => setOcr(false)} title="영수증으로 재고 등록">
        <OcrFlow onDone={() => setOcr(false)} />
      </Modal>
    </div>
  )
}
