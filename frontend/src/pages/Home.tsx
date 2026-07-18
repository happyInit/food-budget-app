import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { img } from '../lib/data'
import { won, type RecommendItem } from '../lib/api'
import { useBudget, useExpenseSummary, useMealRecommend, usePantryItems, useRecipeTeaser, useRecommend, useAddCartItem } from '../lib/queries'
import { storageToZone, toDisplay, type PantryVM, type ZoneKey } from '../lib/pantry'
import FridgeCard from '../components/FridgeCard'
import Modal from '../components/Modal'
import OcrFlow from '../components/forms/OcrFlow'
import BudgetPanel from '../components/settings/BudgetPanel'

const SRC = { kurly: '컬리', oasis: '오아시스' } as Record<string, string>

// 실 날짜 기준 이번 달(YYYY-MM)·남은 일수(오늘 포함) — 하루 권장액 계산용.
const now = new Date()
const MONTH = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
const DAYS_LEFT = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate() - now.getDate() + 1

export default function Home() {
  const nav = useNavigate()

  // ── 실 유저 데이터 ──
  const { data: rows = [] } = usePantryItems()
  const { data: budget } = useBudget()
  const { data: summary } = useExpenseSummary(MONTH)
  const { data: reco } = useMealRecommend()
  const { data: teaserData } = useRecipeTeaser(3)
  const { data: cheapData } = useRecommend(5)
  const addCart = useAddCartItem()
  const [ocr, setOcr] = useState(false)   // 재고 없을 때 '재료 등록' → 영수증 OCR 모달
  const [budgetModal, setBudgetModal] = useState(false)   // 예산 미설정 → 모달로 설정(페이지 이동 X)

  // 냉장고 재고 → zone별 표시 VM (D-day·긴급도는 프론트 파생, Fridge 페이지와 동일 로직·컴포넌트).
  const zones = useMemo(() => {
    const today = new Date()
    const z: Record<ZoneKey, PantryVM[]> = { room: [], fridge: [], freezer: [] }
    for (const r of rows) z[storageToZone(r.storage)].push(toDisplay(r, today))
    return z
  }, [rows])
  const hasPantry = rows.length > 0

  // 예산 — account 예산(있어야 잔여 계산). 잔여·사용률·하루권장은 식비요약 seam에서.
  const hasBudget = budget != null
  const spent = summary?.spent ?? 0
  const budgetAmt = summary?.budget ?? budget?.amount ?? 0
  const remaining = summary?.remaining ?? (hasBudget ? budgetAmt - spent : 0)
  const remainPct = hasBudget && budgetAmt > 0 ? Math.max(0, Math.min(100, Math.round((remaining / budgetAmt) * 100))) : 0
  const perDay = hasBudget && DAYS_LEFT > 0 ? Math.round(Math.max(0, remaining) / DAYS_LEFT) : 0

  // 뭐 해먹지 — 냉장고 재료 기반 실 추천(#32). 없으면 인기 레시피 티저로 폴백.
  const recs = reco?.recommendations ?? []
  const teaser = teaserData?.recipes ?? []
  const cheap = cheapData?.items ?? []

  // 지금 싼 재료 클릭 → (모달) 장바구니 담기 확인 → 담은 뒤 (모달) 장바구니로 이동 확인. 이동만 시키지 않음.
  const [cartAsk, setCartAsk] = useState<RecommendItem | null>(null)   // 1단계: 담기 확인
  const [movedAsk, setMovedAsk] = useState<string | null>(null)       // 2단계: 이동 확인
  const confirmAddCart = () => {
    if (!cartAsk) return
    const nm = cartAsk.canonical_name
    addCart.mutate({ name: nm, item_id: cartAsk.item_id }, {
      onSuccess: () => { setCartAsk(null); setMovedAsk(nm) },
    })
  }

  return (
    <div>
      {/* ═══ 반반 분할: 좌 냉장고 · 우 정보 (반응형: 좁으면 세로 적층) ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(300px,0.92fr) 1.08fr', gap: 20, alignItems: 'stretch' }} className="max-[880px]:!grid-cols-1">
        {/* 좌: 냉장고 — Fridge 페이지와 동일한 FridgeCard(문 달림, 상태만 + 관리 CTA). 우측 컬럼 높이만큼 채움. */}
        <div style={{ height: '100%' }}>
          <FridgeCard
            zones={zones}
            total={rows.length}
            mode="home"
            onManage={() => (hasPantry ? nav('/pantry') : setOcr(true))}
          />
        </div>

        {/* 우: 정보 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
          {/* 예산 */}
          <div onClick={() => (hasBudget ? nav('/expense') : setBudgetModal(true))} style={{ border: '1px solid #E6E6E6', padding: '16px 18px', cursor: 'pointer' }}>
            {hasBudget ? (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: 12.5, color: '#9A9A9A' }}>{now.getMonth() + 1}월 남은 예산</span>
                  <span className="num" style={{ fontSize: 12, color: '#9A9A9A' }}>하루 {won(perDay)}원</span>
                </div>
                <div className="num" style={{ fontSize: 26, fontWeight: 800, color: '#F26419', margin: '4px 0 10px' }}>{won(remaining)}원</div>
                <div style={{ height: 9, background: '#EFEFEF', overflow: 'hidden' }}><div style={{ height: '100%', width: remainPct + '%', background: '#F26419' }} /></div>
              </>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 13.5, color: '#5E5E5E' }}>이번 달 식비 예산을 정하면 남은 예산을 추적해요</span>
                <span style={{ marginLeft: 'auto', fontSize: 12.5, fontWeight: 800, color: '#F26419', whiteSpace: 'nowrap' }}>정하기 →</span>
              </div>
            )}
          </div>

          {/* 오늘 뭐 해먹지 */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
              <h2 style={{ fontSize: 19, margin: 0 }}>{hasPantry ? '이 재료로 뭐 해먹지?' : '오늘 뭐 해먹지?'}</h2>
              <span onClick={() => nav('/mealplan')} style={{ fontSize: 13, color: '#5E5E5E', cursor: 'pointer' }}>더보기 ›</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {recs.length > 0 ? (
                // 냉장고 재료 기반 실 추천 — coverage(보유 커버리지)·추가비 표시.
                recs.slice(0, 3).map((r) => (
                  <div key={r.recipe_id} onClick={() => nav('/recipes/' + r.recipe_id)} style={{ display: 'flex', gap: 12, border: '1px solid #E6E6E6', background: '#fff', cursor: 'pointer' }}>
                    <div className="zoom-wrap" style={{ width: 88, flexShrink: 0, minHeight: 66, background: '#F0F0F0' }}>
                      <div className="zoom" style={{ width: '100%', height: '100%', minHeight: 66, background: `center/cover no-repeat url("${r.image_url || img(r.recipe_id)}")` }} />
                    </div>
                    <div style={{ padding: '10px 12px 10px 0', minWidth: 0 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 700, lineHeight: 1.35, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</div>
                      <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 5 }}>냉장고 재료 {Math.round(r.coverage * 100)}% 활용{r.expiring_used > 0 ? ` · 임박 ${r.expiring_used}종` : ''}</div>
                      <div className="num" style={{ fontSize: 12.5, fontWeight: 800, color: r.est_cost ? '#1E5F96' : '#20A24A', marginTop: 6 }}>{r.est_cost ? `재료비 약 ${won(r.est_cost)}원` : '가격 정보 없음'}</div>
                    </div>
                  </div>
                ))
              ) : (
                // 재고 없음 → 인기 레시피 티저(폴백).
                teaser.map((r) => (
                  <div key={r.id} onClick={() => nav('/recipes/' + r.id)} style={{ display: 'flex', gap: 12, border: '1px solid #E6E6E6', background: '#fff', cursor: 'pointer' }}>
                    <div className="zoom-wrap" style={{ width: 88, flexShrink: 0, minHeight: 66, background: '#F0F0F0' }}>
                      <div className="zoom" style={{ width: '100%', height: '100%', minHeight: 66, background: `center/cover no-repeat url("${r.image_url || img(r.id)}")` }} />
                    </div>
                    <div style={{ padding: '10px 12px 10px 0', minWidth: 0 }}>
                      <div style={{ fontSize: 13.5, fontWeight: 700, lineHeight: 1.35, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</div>
                      <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 5 }}>{[r.cooking_time].filter(Boolean).join(' · ') || '만개의레시피'}</div>
                    </div>
                  </div>
                ))
              )}
              {recs.length === 0 && teaser.length === 0 && (
                <div style={{ border: '1px dashed #E6E6E6', padding: '18px 16px', fontSize: 13, color: '#9A9A9A', textAlign: 'center' }}>
                  냉장고를 채우면 재료로 만들 수 있는 레시피를 추천해요.
                </div>
              )}
            </div>
          </div>

          {/* 지금 싼 재료 — 클릭 시 장바구니 담기(이동 안 함) */}
          <div>
            <h2 style={{ fontSize: 19, margin: '0 0 4px' }}>지금 싼 재료</h2>
            <div style={{ fontSize: 11, color: '#9A9A9A', margin: '0 0 10px' }}>마켓컬리·오아시스마켓 중 최저가 · 누르면 장바구니에 담아요</div>
            <div style={{ border: '1px solid #E6E6E6' }}>
              {cheap.length === 0 && (
                <div style={{ padding: '14px', fontSize: 12.5, color: '#9A9A9A' }}>싼 재료 정보를 불러오는 중…</div>
              )}
              {cheap.map((c, i) => (
                <div key={c.item_id} onClick={() => setCartAsk(c)} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 14px', borderTop: i ? '1px solid #EFEFEF' : 'none', cursor: 'pointer' }}>
                  <span style={{ fontSize: 13.5, fontWeight: 700, color: '#17264A' }}>{c.canonical_name}</span>
                  <span style={{ fontSize: 11, color: '#9A9A9A' }}>{SRC[c.cheaper_source] ?? c.cheaper_source}</span>
                  <span className="num" style={{ marginLeft: 'auto', fontSize: 14, fontWeight: 800, color: '#17264A' }}>{won(c.cheaper_krw_per_100g)}<span style={{ fontSize: 10.5, color: '#9A9A9A', fontWeight: 400 }}> 원/100g</span></span>
                  <span className="num" style={{ fontSize: 11.5, fontWeight: 800, color: '#F04452', width: 40, textAlign: 'right' }}>↓{c.saving_pct}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* item 1: 싼 재료 담기 확인(모달) → 담은 뒤 이동 확인(모달) */}
      <Modal open={!!cartAsk} onClose={() => setCartAsk(null)} title="장바구니 담기">
        {cartAsk && (
          <div>
            <p style={{ fontSize: 14, color: '#17264A', margin: '0 0 16px', lineHeight: 1.6 }}>
              <b>{cartAsk.canonical_name}</b>을(를) 장바구니에 담을까요?
            </p>
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => setCartAsk(null)} style={{ flex: 1, padding: 12, border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>취소</button>
              <button onClick={confirmAddCart} disabled={addCart.isPending} style={{ flex: 2, padding: 12, border: 'none', background: '#F26419', color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>{addCart.isPending ? '담는 중…' : '장바구니에 담기'}</button>
            </div>
          </div>
        )}
      </Modal>
      <Modal open={!!movedAsk} onClose={() => setMovedAsk(null)} title="담았어요">
        {movedAsk && (
          <div>
            <p style={{ fontSize: 14, color: '#17264A', margin: '0 0 16px', lineHeight: 1.6 }}>
              <b>{movedAsk}</b>을(를) 장바구니에 담았어요. 장바구니로 이동할까요?
            </p>
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => setMovedAsk(null)} style={{ flex: 1, padding: 12, border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>계속 볼게요</button>
              <button onClick={() => { setMovedAsk(null); nav('/cart') }} style={{ flex: 2, padding: 12, border: 'none', background: '#F26419', color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>장바구니로 이동</button>
            </div>
          </div>
        )}
      </Modal>

      <Modal open={ocr} maxWidth={820} onClose={() => setOcr(false)} title="영수증으로 재고 등록">
        <OcrFlow onClose={() => setOcr(false)} />
      </Modal>

      <Modal open={budgetModal} onClose={() => setBudgetModal(false)} title="월 식비 예산 설정">
        <BudgetPanel onSaved={() => setBudgetModal(false)} />
      </Modal>
    </div>
  )
}
