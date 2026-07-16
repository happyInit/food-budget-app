import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { img } from '../lib/data'
import { won, type MealRecommendation } from '../lib/api'
import { useMealRecommend, useRecipe } from '../lib/queries'

const MAX_PLATES = 9 // 히어로 1 + 규칙 그리드 8

// 데스크톱(≥900px) = 좌측 슬라이드 사이드바 / 모바일 = 풀스크린. AppShell과 동일 브레이크포인트.
function useIsDesktop() {
  const [d, setD] = useState(() => window.matchMedia('(min-width: 900px)').matches)
  useEffect(() => {
    const m = window.matchMedia('(min-width: 900px)')
    const on = () => setD(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [])
  return d
}

// 사이드바 본문 — rec(추천)로 즉시 렌더 후 상세(useRecipe)로 재료·단계 보강.
function PanelBody({ rec }: { rec: MealRecommendation }) {
  const { data: detail, isLoading } = useRecipe(rec.recipe_id)
  const meta = [detail?.cooking_time, detail?.level_nm, detail?.serving].filter(Boolean).join(' · ')
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      {/* 본문 (스크롤) */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '22px 24px 8px' }}>
        {/* 썸네일 — 풀블리드 대신 라운드 카드(과확대 완화) */}
        <div style={{ position: 'relative', width: '100%', aspectRatio: '16 / 10', borderRadius: 16, overflow: 'hidden', background: `#EDE7DD center/cover no-repeat url("${rec.image_url || img(rec.recipe_id, 640)}")` }}>
          <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(to top, rgba(0,0,0,.28), transparent 42%)' }} />
          <span style={{ position: 'absolute', left: 14, bottom: 12, padding: '5px 11px', fontSize: 12, fontWeight: 700, background: '#1E5F96', color: '#fff', borderRadius: 999 }}>
            재료 {Math.round(rec.coverage * 100)}% 보유
          </span>
        </div>

        <h2 style={{ fontSize: 21, fontWeight: 800, letterSpacing: '-.4px', margin: '18px 0 6px', lineHeight: 1.3 }}>{rec.name}</h2>
        <div style={{ fontSize: 13, color: '#9A9A9A', marginBottom: 18 }}>{meta || (isLoading ? '레시피 정보를 불러오는 중…' : '만개의레시피')}</div>

        {rec.est_cost != null && (
          <div style={{ display: 'inline-block', background: '#F7F4EF', padding: '10px 15px', borderRadius: 10, marginBottom: 18 }}>
            <div style={{ fontSize: 11, color: '#9A9A9A', marginBottom: 3 }}>예상 부족분 비용</div>
            <div className="num" style={{ fontSize: 16, fontWeight: 800, color: '#17264A' }}>{won(rec.est_cost)}원</div>
          </div>
        )}

        {detail?.ingredients?.length ? (
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 13.5, fontWeight: 800, color: '#17264A', marginBottom: 9 }}>재료 {detail.ingredients.length}</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7 }}>
              {detail.ingredients.slice(0, 16).map((ing, i) => (
                <span key={i} style={{ fontSize: 12.5, color: '#5E5E5E', background: '#F2ECE3', padding: '5px 11px', borderRadius: 999 }}>
                  {ing.ingredient_name}{ing.quantity ? ` ${ing.quantity}` : ''}
                </span>
              ))}
              {detail.ingredients.length > 16 && <span style={{ fontSize: 12, color: '#9A9A9A', padding: '5px 4px' }}>+{detail.ingredients.length - 16}</span>}
            </div>
          </div>
        ) : isLoading ? (
          <div style={{ color: '#9A9A9A', fontSize: 13, marginBottom: 20 }}>재료를 불러오는 중…</div>
        ) : null}

        {detail?.steps?.length ? (
          <div>
            <div style={{ fontSize: 13.5, fontWeight: 800, color: '#17264A', marginBottom: 9 }}>조리 순서 {detail.steps.length}단계</div>
            <ol style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 11 }}>
              {detail.steps.slice(0, 4).map((s, i) => (
                <li key={i} style={{ display: 'flex', gap: 11, fontSize: 13, color: '#5E5E5E', lineHeight: 1.55 }}>
                  <span style={{ flexShrink: 0, width: 21, height: 21, borderRadius: '50%', background: '#F26419', color: '#fff', fontSize: 11, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{i + 1}</span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>{s.description}</span>
                </li>
              ))}
              {detail.steps.length > 4 && <li style={{ fontSize: 12, color: '#9A9A9A', paddingLeft: 32 }}>…전체 보기에서 이어서</li>}
            </ol>
          </div>
        ) : null}
      </div>
    </div>
  )
}

// 좌측 슬라이드 패널 — 항상 DOM에 두고 open 으로 애니메이션(입·퇴장). 바깥 클릭=닫힘.
function RecipePanel({
  rec,
  open,
  isDesktop,
  onClose,
}: {
  rec: MealRecommendation | null
  open: boolean
  isDesktop: boolean
  onClose: () => void
}) {
  const nav = useNavigate()
  return (
    <>
      {/* 백드롭 — 레시피 영역 '이외'를 덮음. 클릭 시 닫힘. */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, zIndex: 49,
          background: 'rgba(20,20,20,.42)',
          opacity: open ? 1 : 0,
          pointerEvents: open ? 'auto' : 'none',
          transition: 'opacity .3s ease',
        }}
      />
      {/* 사이드바 — 데스크톱 ~42vw(과하지 않게), 모바일 풀스크린. 왼쪽에서 슬라이드. */}
      <aside
        style={{
          position: 'fixed', top: 0, left: 0, bottom: 0, zIndex: 50,
          width: isDesktop ? 'min(42vw, 560px)' : '100vw',
          background: '#fff',
          boxShadow: '18px 0 52px -18px rgba(23,38,74,.34)',
          transform: open ? 'translateX(0)' : 'translateX(-100%)',
          transition: 'transform .34s cubic-bezier(.4,0,.2,1)',
          display: 'flex', flexDirection: 'column',
        }}
      >
        <button onClick={onClose} aria-label="닫기"
          style={{ position: 'absolute', top: 14, right: 14, zIndex: 2, width: 36, height: 36, borderRadius: '50%', border: 'none', background: 'rgba(0,0,0,.45)', color: '#fff', fontSize: 17, cursor: 'pointer', lineHeight: 1 }}>
          ✕
        </button>
        {rec && <PanelBody rec={rec} />}
        {rec && (
          <div style={{ flexShrink: 0, borderTop: '1px solid #EFEFEF', padding: '14px 24px' }}>
            <button onClick={() => nav('/recipes/' + rec.recipe_id)}
              style={{ width: '100%', padding: '14px 0', border: 'none', background: '#F26419', color: '#fff', fontSize: 14.5, fontWeight: 800, cursor: 'pointer', borderRadius: 10 }}>
              레시피 전체 보기 →
            </button>
          </div>
        )}
      </aside>
    </>
  )
}

export default function MealPlan() {
  const nav = useNavigate()
  const isDesktop = useIsDesktop()
  const [active, setActive] = useState(-1)                          // 룰렛 하이라이트
  const [openRec, setOpenRec] = useState<MealRecommendation | null>(null) // 패널이 보여줄 추천(닫아도 유지 → 퇴장 애니메이션)
  const [panelOpen, setPanelOpen] = useState(false)                // 패널 열림/닫힘(슬라이드)
  const [spinning, setSpinning] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  const { data: reco, isLoading, error } = useMealRecommend()

  useEffect(() => () => window.clearInterval(timer.current), [])

  const recs = (reco?.recommendations ?? []).slice(0, MAX_PLATES)
  const hasPlates = recs.length > 0
  const hero = recs[0]                       // 1순위(최고 보유%) = 히어로
  const rest = recs.slice(1)                 // 나머지 = 우측 클러스터
  const heroSize = isDesktop ? 320 : 216     // 히어로 고정 대형
  const gridSize = isDesktop ? 128 : 92      // 규칙 그리드 접시(균일 크기)

  const heroOn = !!hero && (active === 0 || (panelOpen && openRec?.recipe_id === hero.recipe_id))

  const openPlate = (p: MealRecommendation) => { setOpenRec(p); setPanelOpen(true) }
  const closePanel = () => setPanelOpen(false)

  const clusterPlate = (p: MealRecommendation, k: number) => {
    const idx = k + 1 // recs 내 실제 인덱스(룰렛 하이라이트)
    const on = active === idx || (panelOpen && openRec?.recipe_id === p.recipe_id)
    return (
      <button
        key={p.recipe_id}
        onClick={() => openPlate(p)}
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', border: 'none', background: 'transparent', cursor: 'pointer', padding: 0, transition: 'transform .2s ease', transform: on ? 'scale(1.07)' : 'none' }}
      >
        <div style={{ width: gridSize, height: gridSize, borderRadius: '50%', background: `#EDE7DD center/cover no-repeat url("${p.image_url || img(p.recipe_id, 400)}")`, border: '4px solid #fff', transition: 'box-shadow .2s ease', boxShadow: on ? '0 0 0 4px #F26419, 0 18px 30px -12px rgba(60,48,36,.34)' : '0 12px 24px -14px rgba(60,48,36,.28)' }} />
        <div style={{ marginTop: 10, fontSize: 12.5, fontWeight: 700, color: '#17264A', maxWidth: gridSize + 26, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</div>
        <div className="num" style={{ marginTop: 2, fontSize: 11, fontWeight: 700, color: '#1E5F96' }}>재료 {Math.round(p.coverage * 100)}% 보유</div>
      </button>
    )
  }

  const spin = () => {
    if (spinning || !hasPlates) return
    setSpinning(true)
    setPanelOpen(false)
    let i = 0
    let step = 60
    const total = 28 + Math.floor(Math.random() * recs.length)
    const tick = () => {
      setActive(i % recs.length)
      i++
      if (i >= total) {
        window.clearInterval(timer.current)
        const win = (i - 1) % recs.length
        setActive(win)
        setSpinning(false)
        openPlate(recs[win])                                       // 당첨 접시를 사이드바로 열어줌
        return
      }
      if (i > total - 8) {
        step += 40
        window.clearInterval(timer.current)
        timer.current = window.setInterval(tick, step)
      }
    }
    timer.current = window.setInterval(tick, step)
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>뭐 해먹지?</h1>
          <p style={{ fontSize: 13.5, color: '#5E5E5E', margin: '6px 0 0' }}>냉장고 재료로 만들 수 있는 추천이에요. 접시가 클수록 재료를 많이 갖고 있어요. 누르면 옆에서 레시피가 열려요.</p>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ padding: '7px 13px', fontSize: 12.5, fontWeight: 700, background: '#FDECEC', color: '#F04452' }}>임박 재료 우선</span>
          {hasPlates && <span style={{ padding: '7px 13px', fontSize: 12.5, fontWeight: 700, background: '#E7EFF8', color: '#1E5F96' }}>추천 {recs.length}개</span>}
        </div>
      </div>

      {isLoading && <div style={{ color: '#9A9A9A', fontSize: 13.5, padding: '8px 2px', marginBottom: 14 }}>냉장고 재료로 추천을 계산하는 중…</div>}
      {error && <div style={{ color: '#F04452', fontSize: 13.5, padding: '8px 2px', marginBottom: 14 }}>추천 서버에 연결할 수 없어요 ({(error as Error).message})</div>}

      {/* 추천 없음 → 냉장고 채우기 안내 (mock 없음) */}
      {!isLoading && !error && !hasPlates && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, background: '#F2ECE3', border: '1px solid #E6E6E6', padding: '56px 24px' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#17264A' }}>아직 추천할 레시피가 없어요</div>
          <div style={{ fontSize: 13, color: '#5E5E5E', textAlign: 'center', maxWidth: 320, lineHeight: 1.6 }}>
            {reco?.note?.includes('unavailable')
              ? '냉장고 서비스에 연결되면 재료 기반으로 추천해요.'
              : '냉장고에 재료를 채우면 그 재료로 만들 수 있는 레시피를 임박 재료 우선으로 추천해요.'}
          </div>
          <button onClick={() => nav('/pantry')} style={{ padding: '13px 26px', border: 'none', background: '#F26419', color: '#fff', fontSize: 14, fontWeight: 800, cursor: 'pointer' }}>냉장고 채우기 →</button>
        </div>
      )}

      {/* 히어로 + 클러스터 (에디토리얼) · 1순위는 크게, 나머지는 크기=보유% */}
      {hasPlates && (
        <>
          <div style={{ background: '#F2ECE3', border: '1px solid #E6E6E6', padding: isDesktop ? '38px 34px 34px' : '26px 18px 30px' }}>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: '#A89B88', letterSpacing: '.5px', marginBottom: isDesktop ? 26 : 18 }}>
              오늘의 추천 {recs.length}접시 · 마음에 드는 걸 고르거나 룰렛으로 정해보세요
            </div>
            <div style={{ display: 'flex', flexDirection: isDesktop ? 'row' : 'column', alignItems: 'center', gap: isDesktop ? 44 : 30, minHeight: isDesktop ? 360 : undefined }}>
              {/* 히어로 — 1순위 추천 */}
              {hero && (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
                  <span style={{ marginBottom: 12, padding: '5px 12px', borderRadius: 999, fontSize: 11.5, fontWeight: 800, letterSpacing: '.3px', background: '#17264A', color: '#fff' }}>⭐ 오늘의 1순위</span>
                  <button onClick={() => openPlate(hero)} style={{ border: 'none', background: 'transparent', cursor: 'pointer', padding: 0, transition: 'transform .2s ease', transform: heroOn ? 'scale(1.04)' : 'none' }}>
                    <div style={{ width: heroSize, height: heroSize, borderRadius: '50%', background: `#EDE7DD center/cover no-repeat url("${hero.image_url || img(hero.recipe_id, 640)}")`, border: '5px solid #fff', transition: 'box-shadow .2s ease', boxShadow: heroOn ? '0 0 0 5px #F26419, 0 30px 50px -14px rgba(60,48,36,.4)' : '0 26px 44px -16px rgba(60,48,36,.36)' }} />
                  </button>
                  <div style={{ marginTop: 16, fontSize: 17, fontWeight: 800, color: '#17264A', textAlign: 'center', maxWidth: heroSize }}>{hero.name}</div>
                  <div className="num" style={{ marginTop: 3, fontSize: 12.5, fontWeight: 700, color: '#1E5F96' }}>재료 {Math.round(hero.coverage * 100)}% 보유{hero.est_cost != null ? ` · ${won(hero.est_cost)}원` : ''}</div>
                </div>
              )}

              {/* 나머지 — 규칙 그리드(균일 크기·정렬). 데스크톱 4열 / 모바일 2열 */}
              {rest.length > 0 && (
                <div style={{ flex: 1, display: 'grid', gridTemplateColumns: `repeat(${isDesktop ? 4 : 2}, 1fr)`, gap: isDesktop ? '30px 12px' : '22px 8px', justifyItems: 'center', alignItems: 'end', width: '100%' }}>
                  {rest.map(clusterPlate)}
                </div>
              )}
            </div>
          </div>

          {/* 룰렛 버튼 */}
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: 18 }}>
            <button onClick={spin} disabled={spinning} style={{ padding: '15px 32px', border: 'none', background: '#17264A', color: '#fff', fontSize: 15, fontWeight: 800, cursor: spinning ? 'default' : 'pointer', opacity: spinning ? 0.75 : 1, boxShadow: '0 10px 24px rgba(23,38,74,.24)' }}>
              {spinning ? '고르는 중…' : '룰렛으로 정하기'}
            </button>
          </div>
        </>
      )}

      {/* 사이드바(좌측 슬라이드) 레시피 패널 */}
      <RecipePanel rec={openRec} open={panelOpen} isDesktop={isDesktop} onClose={closePanel} />
    </div>
  )
}
