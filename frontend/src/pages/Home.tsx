import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { img } from '../lib/data'
import { won } from '../lib/api'
import { useBudget, useExpenseSummary, useMealRecommend, usePantryItems, usePrefetchRecipe, useRecipeTeaser, useRecommend } from '../lib/queries'
import { storageToZone, toDisplay, type PantryVM, type ZoneKey } from '../lib/pantry'

const DISPLAY = { fontFamily: 'var(--font-display)' } as const
const SRC = { kurly: '컬리', oasis: '오아시스' } as Record<string, string>
const URG = { danger: { c: '#F04452', bg: '#FDECEC' }, warn: { c: '#F26419', bg: '#FCEBDD' }, ok: { c: '#1E5F96', bg: '#E7EFF8' } }

// 실 날짜 기준 이번 달(YYYY-MM)·남은 일수(오늘 포함) — 하루 권장액 계산용.
const now = new Date()
const MONTH = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
const DAYS_LEFT = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate() - now.getDate() + 1

function MiniChip({ it }: { it: PantryVM }) {
  const u = URG[it.urg]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7, background: '#fff', border: '1px solid #E6E6E6', padding: '5px 8px' }}>
      <div style={{ width: 22, height: 22, borderRadius: '50%', flexShrink: 0, background: `#F0F0F0 center/cover no-repeat url("${img(it.p, 60)}")` }} />
      <span style={{ fontSize: 11.5, fontWeight: 600, color: '#17264A', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.name}</span>
      <span className="num" style={{ marginLeft: 'auto', padding: '1px 5px', fontSize: 9.5, fontWeight: 800, background: u.bg, color: u.c, whiteSpace: 'nowrap' }}>{it.dday}</span>
    </div>
  )
}

// 냉장고 한 칸(냉장/냉동) — 비어있으면 채우기 placeholder.
function Compartment({ label, temp, tint, items }: { label: string; temp: string; tint: string; items: PantryVM[] }) {
  const empty = items.length === 0
  return (
    <div style={{ background: tint, border: '1px solid rgba(0,0,0,.06)', padding: '10px 12px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, marginBottom: 8 }}>
        <span style={{ fontSize: 12.5, fontWeight: 800, color: '#17264A' }}>{label}</span>
        <span style={{ fontSize: 10.5, color: '#9AA3AF' }}>{temp}</span>
        {!empty && <span style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, color: '#9AA3AF' }}>{items.length}개</span>}
      </div>
      {empty ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          {[0, 1, 2, 3].map((i) => (
            <div key={i} style={{ height: 30, border: '1.5px dashed #D6D6D6', background: 'rgba(255,255,255,.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#C4C4C4', fontSize: 12 }}>＋</div>
          ))}
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 6 }}>{items.map((it) => <MiniChip key={it.id} it={it} />)}</div>
      )}
    </div>
  )
}

// 좌측 냉장고 비주얼 — 실 재고(zones) 기반. 문을 클릭해서 열면 냉장/냉동 내부가 보인다.
function FridgeVisual({ zones, total, onOpen }: { zones: Record<ZoneKey, PantryVM[]>; total: number; onOpen: () => void }) {
  const [doorOpen, setDoorOpen] = useState(false)
  const filled = total > 0
  const doorFace: React.CSSProperties = {
    position: 'absolute', top: 14, bottom: 14, width: 'calc(50% - 14px)',
    background: 'linear-gradient(180deg,#EEF1F5,#DBE1E9)',
    transition: 'transform .7s cubic-bezier(.45,.05,.2,1)',
    boxShadow: doorOpen ? 'none' : '0 14px 30px rgba(23,38,74,.14)',
    display: 'flex', alignItems: 'center', cursor: doorOpen ? 'default' : 'pointer',
    pointerEvents: doorOpen ? 'none' : 'auto', zIndex: 6,
  }
  return (
    <div style={{ border: '1px solid #C6CDD7', borderRadius: 16, overflow: 'hidden', background: 'linear-gradient(180deg,#EEF1F5,#DFE4EB)', boxShadow: '0 20px 44px rgba(23,38,74,.14)' }}>
      {/* 상단 손잡이 바 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 9, background: '#17264A', color: '#fff', padding: '13px 16px' }}>
        <span style={{ ...DISPLAY, fontSize: 17 }}>내 냉장고</span>
        <span style={{ fontSize: 11.5, color: 'rgba(255,255,255,.6)' }}>{filled ? `${total}종 보유` : '비어있어요'}</span>
        {doorOpen ? (
          <span onClick={() => setDoorOpen(false)} style={{ marginLeft: 'auto', fontSize: 11.5, fontWeight: 700, color: '#fff', cursor: 'pointer', border: '1px solid rgba(255,255,255,.32)', padding: '4px 10px' }}>문 닫기</span>
        ) : (
          <div style={{ marginLeft: 'auto', width: 30, height: 6, borderRadius: 3, background: 'rgba(255,255,255,.32)' }} />
        )}
      </div>

      {/* 실온·팬트리 = 냉장고 본체 위 선반 (문 밖·항상 보임) */}
      <div style={{ background: 'linear-gradient(180deg,#F0EBE2,#E4DCCE)', borderBottom: '1px solid #D8CDB8', padding: '11px 14px 13px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, marginBottom: 8 }}>
          <span style={{ fontSize: 12.5, fontWeight: 800, color: '#7A6A48' }}>실온·팬트리</span>
          <span style={{ fontSize: 10.5, color: '#A99A78' }}>20℃ · 팬트리 선반</span>
          {zones.room.length > 0 && <span style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, color: '#A99A78' }}>{zones.room.length}개</span>}
        </div>
        {zones.room.length === 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
            {[0, 1].map((i) => (
              <div key={i} style={{ height: 30, border: '1.5px dashed #CDBF9E', background: 'rgba(255,255,255,.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#BBA97F', fontSize: 12 }}>＋</div>
            ))}
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 6 }}>{zones.room.map((it) => <MiniChip key={it.id} it={it} />)}</div>
        )}
      </div>
      {/* 선반–본체 사이 나무 단 */}
      <div style={{ height: 8, background: 'linear-gradient(180deg,#D8CDB8,#CFC3AC)' }} />

      {/* 냉장고 본체: 문 + 내부(냉장·냉동) 칸 (클릭해서 열기) */}
      <div style={{ position: 'relative', perspective: 1600, padding: 14 }}>
        {/* 내부 칸 (문 뒤) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Compartment label="냉장실" temp="3℃" tint="rgba(255,255,255,.6)" items={zones.fridge} />
          <Compartment label="냉동실" temp="−18℃" tint="#EAF6FF" items={zones.freezer} />
        </div>

        {/* 왼쪽 문 */}
        <div onClick={() => !doorOpen && setDoorOpen(true)}
          style={{ ...doorFace, left: 14, borderRight: '1px solid #CBD2DC', borderRadius: '10px 0 0 10px', justifyContent: 'flex-end', transformOrigin: 'left center', transform: doorOpen ? 'rotateY(-118deg)' : 'rotateY(0deg)' }}>
          <div style={{ width: 5, height: 96, borderRadius: 3, background: 'linear-gradient(90deg,rgba(0,0,0,.16),rgba(0,0,0,.03))', marginRight: 12 }} />
        </div>
        {/* 오른쪽 문 */}
        <div onClick={() => !doorOpen && setDoorOpen(true)}
          style={{ ...doorFace, right: 14, borderRadius: '0 10px 10px 0', justifyContent: 'flex-start', transformOrigin: 'right center', transform: doorOpen ? 'rotateY(118deg)' : 'rotateY(0deg)' }}>
          <div style={{ width: 5, height: 96, borderRadius: 3, background: 'linear-gradient(270deg,rgba(0,0,0,.16),rgba(0,0,0,.03))', marginLeft: 12 }} />
        </div>

        {/* 닫힘 안내 */}
        <div style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, pointerEvents: 'none', zIndex: 7, opacity: doorOpen ? 0 : 1, transition: 'opacity .3s ease' }}>
          <div style={{ background: '#F26419', color: '#fff', fontSize: 12.5, fontWeight: 800, padding: '9px 16px', textAlign: 'center' }}>냉장고 문을 클릭해서 열어보세요</div>
          <span style={{ fontSize: 22, color: '#F26419' }}>▾</span>
        </div>
      </div>

      {/* 하단 CTA */}
      <div style={{ padding: '0 14px 14px' }}>
        <button onClick={onOpen} style={{ width: '100%', padding: '13px', border: 'none', background: '#F26419', color: '#fff', ...DISPLAY, fontSize: 15, cursor: 'pointer' }}>
          {filled ? '냉장고 관리하기 →' : '영수증 찍어 채우기'}
        </button>
      </div>
    </div>
  )
}

export default function Home() {
  const nav = useNavigate()
  const prefetch = usePrefetchRecipe()

  // ── 실 유저 데이터 ──
  const { data: rows = [] } = usePantryItems()
  const { data: budget } = useBudget()
  const { data: summary } = useExpenseSummary(MONTH)
  const { data: reco } = useMealRecommend()
  const { data: teaserData } = useRecipeTeaser(3)
  const { data: cheapData } = useRecommend(5)

  // 냉장고 재고 → zone별 표시 VM (D-day·긴급도는 프론트 파생, Fridge 페이지와 동일 로직).
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

  return (
    <div>
      {/* ═══ 반반 분할: 좌 냉장고 · 우 정보 (반응형: 좁으면 세로 적층) ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(300px,0.92fr) 1.08fr', gap: 20, alignItems: 'start' }} className="max-[880px]:!grid-cols-1">
        {/* 좌: 냉장고 */}
        <div style={{ position: 'sticky', top: 80 }} className="max-[880px]:!static">
          <FridgeVisual zones={zones} total={rows.length} onOpen={() => nav(hasPantry ? '/pantry' : '/ocr')} />
        </div>

        {/* 우: 정보 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
          {/* 예산 */}
          <div onClick={() => nav(hasBudget ? '/expense' : '/budget')} style={{ border: '1px solid #E6E6E6', padding: '16px 18px', cursor: 'pointer' }}>
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
                  <div key={r.recipe_id} onClick={() => nav('/recipes/' + r.recipe_id)} onMouseEnter={() => prefetch(r.recipe_id)} style={{ display: 'flex', gap: 12, border: '1px solid #E6E6E6', background: '#fff', cursor: 'pointer' }}>
                    <div className="zoom-wrap" style={{ width: 88, flexShrink: 0, minHeight: 66, background: '#F0F0F0' }}>
                      <div className="zoom" style={{ width: '100%', height: '100%', minHeight: 66, background: `center/cover no-repeat url("${img(r.recipe_id)}")` }} />
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
                  <div key={r.id} onClick={() => nav('/recipes/' + r.id)} onMouseEnter={() => prefetch(r.id)} style={{ display: 'flex', gap: 12, border: '1px solid #E6E6E6', background: '#fff', cursor: 'pointer' }}>
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

          {/* 지금 싼 재료 */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
              <h2 style={{ fontSize: 19, margin: 0 }}>지금 싼 재료</h2>
              <span onClick={() => nav('/hotdeal')} style={{ fontSize: 13, color: '#5E5E5E', cursor: 'pointer' }}>시세 ›</span>
            </div>
            <div style={{ border: '1px solid #E6E6E6' }}>
              {cheap.length === 0 && (
                <div style={{ padding: '14px', fontSize: 12.5, color: '#9A9A9A' }}>시세 정보를 불러오는 중…</div>
              )}
              {cheap.map((c, i) => (
                <div key={c.item_id} onClick={() => nav('/hotdeal')} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '11px 14px', borderTop: i ? '1px solid #EFEFEF' : 'none', cursor: 'pointer' }}>
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
    </div>
  )
}
