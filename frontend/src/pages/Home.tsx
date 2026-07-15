import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { pantry, img, type PantryItem } from '../lib/data'
import { won } from '../lib/api'
import { useRecipeTeaser, useRecommend, usePrefetchRecipe } from '../lib/queries'

const DISPLAY = { fontFamily: 'var(--font-display)' } as const
const BUDGET = { remain: 182400, total: 300000, pct: 61, perDay: 6080 }
const SRC = { kurly: '컬리', oasis: '오아시스' } as Record<string, string>
const URG = { danger: { c: '#F04452', bg: '#FDECEC' }, warn: { c: '#F26419', bg: '#FCEBDD' }, ok: { c: '#1E5F96', bg: '#E7EFF8' } }

function MiniChip({ it }: { it: PantryItem }) {
  const u = URG[it.urg]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7, background: '#fff', border: '1px solid #E6E6E6', padding: '5px 8px' }}>
      <div style={{ width: 22, height: 22, borderRadius: '50%', flexShrink: 0, background: `#F0F0F0 center/cover no-repeat url("${img(it.p, 60)}")` }} />
      <span style={{ fontSize: 11.5, fontWeight: 600, color: '#17264A', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.name}</span>
      <span className="num" style={{ marginLeft: 'auto', padding: '1px 5px', fontSize: 9.5, fontWeight: 800, background: u.bg, color: u.c, whiteSpace: 'nowrap' }}>{it.dday}</span>
    </div>
  )
}

// 냉장고 한 칸(냉장/냉동)
function Compartment({ label, temp, tint, items, empty }: { label: string; temp: string; tint: string; items: PantryItem[]; empty: boolean }) {
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
        <div style={{ display: 'grid', gap: 6 }}>{items.map((it) => <MiniChip key={it.name} it={it} />)}</div>
      )}
    </div>
  )
}

// 좌측 냉장고 비주얼 (내 냉장고 페이지 톤·문 스윙 동일)
function FridgeVisual({ stage, onOpen }: { stage: 0 | 1; onOpen: () => void }) {
  const [doorOpen, setDoorOpen] = useState(false)
  const total = pantry.room.length + pantry.fridge.length + pantry.freezer.length
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
        <span style={{ fontSize: 11.5, color: 'rgba(255,255,255,.6)' }}>{stage ? `${total}종 보유` : '비어있어요'}</span>
        {doorOpen ? (
          <span onClick={() => setDoorOpen(false)} style={{ marginLeft: 'auto', fontSize: 11.5, fontWeight: 700, color: '#fff', cursor: 'pointer', border: '1px solid rgba(255,255,255,.32)', padding: '4px 10px' }}>문 닫기</span>
        ) : (
          <div style={{ marginLeft: 'auto', width: 30, height: 6, borderRadius: 3, background: 'rgba(255,255,255,.32)' }} />
        )}
      </div>

      {/* 실온·팬트리 = 냉장고 본체 위 선반 (내 냉장고 페이지와 동일 배치 — 문 밖·항상 보임) */}
      <div style={{ background: 'linear-gradient(180deg,#F0EBE2,#E4DCCE)', borderBottom: '1px solid #D8CDB8', padding: '11px 14px 13px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, marginBottom: 8 }}>
          <span style={{ fontSize: 12.5, fontWeight: 800, color: '#7A6A48' }}>실온·팬트리</span>
          <span style={{ fontSize: 10.5, color: '#A99A78' }}>20℃ · 팬트리 선반</span>
          {stage === 1 && <span style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, color: '#A99A78' }}>{pantry.room.length}개</span>}
        </div>
        {stage === 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
            {[0, 1].map((i) => (
              <div key={i} style={{ height: 30, border: '1.5px dashed #CDBF9E', background: 'rgba(255,255,255,.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#BBA97F', fontSize: 12 }}>＋</div>
            ))}
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 6 }}>{pantry.room.map((it) => <MiniChip key={it.name} it={it} />)}</div>
        )}
      </div>
      {/* 선반–본체 사이 나무 단 */}
      <div style={{ height: 8, background: 'linear-gradient(180deg,#D8CDB8,#CFC3AC)' }} />

      {/* 냉장고 본체: 문 + 내부(냉장·냉동) 칸 (클릭해서 열기) */}
      <div style={{ position: 'relative', perspective: 1600, padding: 14 }}>
        {/* 내부 칸 (문 뒤) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <Compartment label="냉장실" temp="3℃" tint="rgba(255,255,255,.6)" items={pantry.fridge} empty={stage === 0} />
          <Compartment label="냉동실" temp="−18℃" tint="#EAF6FF" items={pantry.freezer} empty={stage === 0} />
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
          {stage ? '냉장고 관리하기 →' : '영수증 찍어 채우기'}
        </button>
      </div>
    </div>
  )
}

export default function Home() {
  const nav = useNavigate()
  const prefetch = usePrefetchRecipe()
  const [stage, setStage] = useState<0 | 1>(1)
  const { data: rec } = useRecipeTeaser(3)
  const teaser = rec?.recipes ?? []
  const { data: cheapData } = useRecommend(5)
  const cheap = cheapData?.items ?? []

  return (
    <div>
      {/* 데모 토글 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
        <div style={{ display: 'inline-flex', border: '1.5px solid #E6E6E6', fontSize: 12, fontWeight: 700 }}>
          <span style={{ padding: '5px 11px', fontSize: 11, color: '#B5B5B5', alignSelf: 'center' }}>미리보기</span>
          {(['빈 냉장고(신규)', '채워진(기존)'] as const).map((t, i) => (
            <button key={t} onClick={() => setStage(i as 0 | 1)} style={{ padding: '6px 13px', border: 'none', cursor: 'pointer', background: stage === i ? '#17264A' : '#fff', color: stage === i ? '#fff' : '#5E5E5E' }}>{t}</button>
          ))}
        </div>
      </div>

      {/* ═══ 반반 분할: 좌 냉장고 · 우 정보 (반응형: 좁으면 세로 적층) ═══ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(300px,0.92fr) 1.08fr', gap: 20, alignItems: 'start' }} className="max-[880px]:!grid-cols-1">
        {/* 좌: 냉장고 */}
        <div style={{ position: 'sticky', top: 80 }} className="max-[880px]:!static">
          <FridgeVisual stage={stage} onOpen={() => nav(stage ? '/pantry' : '/ocr')} />
        </div>

        {/* 우: 정보 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
          {/* 예산 */}
          <div onClick={() => nav(stage ? '/expense' : '/budget')} style={{ border: '1px solid #E6E6E6', padding: '16px 18px', cursor: 'pointer' }}>
            {stage === 1 ? (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                  <span style={{ fontSize: 12.5, color: '#9A9A9A' }}>7월 남은 예산</span>
                  <span className="num" style={{ fontSize: 12, color: '#9A9A9A' }}>하루 {won(BUDGET.perDay)}원</span>
                </div>
                <div className="num" style={{ fontSize: 26, fontWeight: 800, color: '#F26419', margin: '4px 0 10px' }}>{won(BUDGET.remain)}원</div>
                <div style={{ height: 9, background: '#EFEFEF', overflow: 'hidden' }}><div style={{ height: '100%', width: BUDGET.pct + '%', background: '#F26419' }} /></div>
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
              <h2 style={{ fontSize: 19, margin: 0 }}>{stage ? '이 재료로 뭐 해먹지?' : '오늘 뭐 해먹지?'}</h2>
              <span onClick={() => nav('/mealplan')} style={{ fontSize: 13, color: '#5E5E5E', cursor: 'pointer' }}>더보기 ›</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {teaser.map((r) => (
                <div key={r.id} onClick={() => nav('/recipes/' + r.id)} onMouseEnter={() => prefetch(r.id)} style={{ display: 'flex', gap: 12, border: '1px solid #E6E6E6', background: '#fff', cursor: 'pointer' }}>
                  <div className="zoom-wrap" style={{ width: 88, flexShrink: 0, minHeight: 66, background: '#F0F0F0' }}>
                    <div className="zoom" style={{ width: '100%', height: '100%', minHeight: 66, background: `center/cover no-repeat url("${r.image_url || img(r.id)}")` }} />
                  </div>
                  <div style={{ padding: '10px 12px 10px 0', minWidth: 0 }}>
                    <div style={{ fontSize: 13.5, fontWeight: 700, lineHeight: 1.35, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</div>
                    <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 5 }}>{[r.cooking_time].filter(Boolean).join(' · ') || '만개의레시피'}</div>
                    {stage === 1 && <div className="num" style={{ fontSize: 12.5, fontWeight: 800, color: '#1E5F96', marginTop: 6 }}>냉장고 재료 활용</div>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 지금 싼 재료 */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
              <h2 style={{ fontSize: 19, margin: 0 }}>지금 싼 재료</h2>
              <span onClick={() => nav('/hotdeal')} style={{ fontSize: 13, color: '#5E5E5E', cursor: 'pointer' }}>시세 ›</span>
            </div>
            <div style={{ border: '1px solid #E6E6E6' }}>
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
