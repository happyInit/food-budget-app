import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { img } from '../lib/data'
import { won, type MealRecommendation } from '../lib/api'
import { useMealRecommend, useRecipe } from '../lib/queries'

const MAX_PLATES = 10 // 갤러리 = 딱 10접시(사각형 채움)

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

// 딱 10개 타일을 사각형으로 채우는 고정 배치(순위=index 로 크기 차등, 1순위가 가장 큼).
//   데스크톱 6열×5행(30셀) / 모바일 2열×8행(16셀) — 각 합이 정확히 채워지도록 span 설계.
const SPAN_DESKTOP = [
  { c: 3, r: 2 }, { c: 3, r: 1 }, { c: 3, r: 1 }, { c: 3, r: 1 }, { c: 3, r: 1 },
  { c: 2, r: 1 }, { c: 2, r: 1 }, { c: 2, r: 1 }, { c: 3, r: 1 }, { c: 3, r: 1 },
]
const SPAN_MOBILE = [
  { c: 2, r: 2 }, { c: 1, r: 1 }, { c: 1, r: 1 }, { c: 2, r: 1 }, { c: 1, r: 1 },
  { c: 1, r: 1 }, { c: 2, r: 1 }, { c: 1, r: 1 }, { c: 1, r: 1 }, { c: 2, r: 1 },
]
function spanOf(i: number, isDesktop: boolean): { c: number; r: number } {
  const t = isDesktop ? SPAN_DESKTOP : SPAN_MOBILE
  return t[i] ?? { c: isDesktop ? 2 : 1, r: 1 }
}

export default function MealPlan() {
  const nav = useNavigate()
  const isDesktop = useIsDesktop()
  const [openRec, setOpenRec] = useState<MealRecommendation | null>(null) // 패널이 보여줄 추천
  const [panelOpen, setPanelOpen] = useState(false)
  const [spinning, setSpinning] = useState(false)
  const [winnerId, setWinnerId] = useState<number | null>(null) // 룰렛 당첨 타일
  const [session, setSession] = useState(0) // 등장 세션(증가 = 재등장)
  const [shown, setShown] = useState(false) // 스태거드 등장 트리거
  const timer = useRef<number | undefined>(undefined)
  const { data: reco, isLoading, error } = useMealRecommend()

  const recs = (reco?.recommendations ?? []).slice(0, MAX_PLATES)
  const hasPlates = recs.length > 0

  // 등장 순서(무작위) — 세션마다 새로. order[i] = 타일 i의 등장 순번.
  const order = useMemo(() => {
    const idx = recs.map((_, i) => i)
    for (let i = idx.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      ;[idx[i], idx[j]] = [idx[j], idx[i]]
    }
    const ord = new Array<number>(idx.length)
    idx.forEach((tileIdx, pos) => { ord[tileIdx] = pos })
    return ord
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, recs.length])

  // 세션 변경 시 재등장(hidden → 다음 프레임에 shown)
  useEffect(() => {
    if (!hasPlates) return
    setShown(false)
    const id = requestAnimationFrame(() => requestAnimationFrame(() => setShown(true)))
    return () => cancelAnimationFrame(id)
  }, [session, recs.length, hasPlates])

  // 추천이 도착하면 첫 등장 트리거
  useEffect(() => {
    if (hasPlates) setSession((s) => s + 1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reco])

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const openPlate = (p: MealRecommendation) => { setOpenRec(p); setPanelOpen(true) }
  const closePanel = () => setPanelOpen(false)

  // 룰렛 = 재등장 + 무작위 당첨 → 등장 끝나면 하이라이트 + 패널 오픈
  const spin = () => {
    if (spinning || !hasPlates) return
    setSpinning(true); setWinnerId(null); setPanelOpen(false)
    setSession((s) => s + 1)
    const winner = recs[Math.floor(Math.random() * recs.length)]
    const delay = Math.min((recs.length - 1) * 60 + 720, 1800)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      setWinnerId(winner.recipe_id)
      setSpinning(false)
      openPlate(winner)
    }, delay)
  }

  const tile = (p: MealRecommendation, i: number) => {
    const span = spanOf(i, isDesktop)
    const pos = order[i] ?? 0
    const cov = Math.round(p.coverage * 100)
    const isWinner = winnerId === p.recipe_id
    const isOpen = panelOpen && openRec?.recipe_id === p.recipe_id
    const nameSize = span.r === 2 ? 20 : span.c >= 3 ? 15.5 : 14
    return (
      <button
        key={p.recipe_id}
        onClick={() => openPlate(p)}
        style={{
          position: 'relative', gridColumn: `span ${span.c}`, gridRow: `span ${span.r}`,
          border: 'none', padding: 0, textAlign: 'left', cursor: 'pointer', overflow: 'hidden',
          borderRadius: 6, color: '#fff', background: '#EDE7DD',
          opacity: shown ? 1 : 0,
          transform: shown ? (isWinner ? 'scale(1.015)' : 'none') : 'translateY(20px) scale(.95)',
          transition: 'opacity .55s cubic-bezier(.22,1,.36,1), transform .5s cubic-bezier(.22,1,.36,1), box-shadow .3s ease',
          transitionDelay: shown ? `${pos * 60}ms` : '0ms',
          boxShadow: isWinner
            ? '0 0 0 3px #F26419, 0 18px 34px -16px rgba(60,48,36,.5)'
            : isOpen
              ? '0 0 0 3px #1E5F96, 0 16px 30px -16px rgba(60,48,36,.4)'
              : '0 12px 24px -16px rgba(60,48,36,.38)',
        }}
      >
        {/* 썸네일 */}
        <span style={{ position: 'absolute', inset: 0, background: `#EDE7DD center/cover no-repeat url("${p.image_url || img(p.recipe_id, 640)}")` }} />
        {/* 하단 스크림 */}
        <span style={{ position: 'absolute', inset: 0, background: 'linear-gradient(180deg, rgba(15,10,6,0) 42%, rgba(15,10,6,.72) 100%)' }} />
        {/* 보유율 칩(우상단) */}
        <span style={{ position: 'absolute', top: 9, right: 9, fontSize: 11, fontWeight: 800, padding: '2px 7px', borderRadius: 3, background: cov >= 100 ? '#F26419' : 'rgba(255,255,255,.2)', backdropFilter: 'blur(6px)' }}>{cov}%</span>
        {/* 당첨 태그(좌상단) */}
        {isWinner && <span style={{ position: 'absolute', top: 0, left: 0, fontSize: 10.5, fontWeight: 800, background: '#F26419', color: '#fff', padding: '4px 9px', borderBottomRightRadius: 6 }}>오늘의 선택</span>}
        {/* 캡션 */}
        <span style={{ position: 'absolute', left: 12, right: 12, bottom: 11 }}>
          <span style={{ display: 'block', fontWeight: 800, letterSpacing: '-.3px', lineHeight: 1.16, fontSize: nameSize, textShadow: '0 1px 10px rgba(0,0,0,.42)' }}>{p.name}</span>
          <span style={{ display: 'block', fontSize: 11, fontWeight: 600, opacity: 0.92, marginTop: 3 }}>재료 {cov}% 보유{p.est_cost != null ? ` · 부족분 ${won(p.est_cost)}원` : ''}</span>
        </span>
        {/* 보유율 바 */}
        <span style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 3, background: 'rgba(255,255,255,.22)' }}>
          <span style={{ display: 'block', height: '100%', width: `${cov}%`, background: '#fff' }} />
        </span>
      </button>
    )
  }

  return (
    <div>
      {/* 헤더 — 앱 기본 톤 유지 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>뭐 해먹지?</h1>
          <p style={{ fontSize: 13.5, color: '#5E5E5E', margin: '6px 0 0' }}>냉장고 재료로 만들 수 있는 추천이에요. 큰 접시일수록 재료를 많이 갖고 있어요. 누르면 옆에서 레시피가 열려요.</p>
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

      {/* 컨트롤 + 갤러리 그리드 */}
      {hasPlates && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 12.5, color: '#9A9A9A' }}>고르기 애매하면 <b style={{ color: '#5E5E5E' }}>룰렛</b>으로 정해보세요.</div>
            <button onClick={spin} disabled={spinning}
              style={{ padding: '11px 22px', border: 'none', background: '#17264A', color: '#fff', fontSize: 13.5, fontWeight: 800, cursor: spinning ? 'default' : 'pointer', opacity: spinning ? 0.6 : 1, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <span style={{ display: 'inline-block', transition: 'transform .6s cubic-bezier(.34,1.56,.64,1)', transform: spinning ? 'rotate(720deg)' : 'none' }}>⟳</span>
              {spinning ? '고르는 중…' : '룰렛으로 정하기'}
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: `repeat(${isDesktop ? 6 : 2}, 1fr)`, gridAutoRows: isDesktop ? 120 : 112, gridAutoFlow: 'row dense', gap: isDesktop ? 12 : 10 }}>
            {recs.map(tile)}
          </div>
        </>
      )}

      {/* 사이드바(좌측 슬라이드) 레시피 패널 */}
      <RecipePanel rec={openRec} open={panelOpen} isDesktop={isDesktop} onClose={closePanel} />
    </div>
  )
}
