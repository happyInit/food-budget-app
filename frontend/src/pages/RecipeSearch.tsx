import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { img, DEFAULT_RECIPE_THUMB } from '../lib/data'
import { type RecipeCard } from '../lib/api'
import { useRecipeSearch, useSharedRecipes } from '../lib/queries'

// 실데이터 태그 (10K recipe.cooking_time / level_nm 값 그대로)
const TIME_TAGS = ['10분 이내', '15분 이내', '20분 이내', '30분 이내', '60분 이내']
const LEVEL_TAGS = ['아무나', '초급', '중급']

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{ padding: '7px 14px', fontSize: 13, fontWeight: active ? 700 : 600, border: active ? '1.5px solid #F26419' : '1.5px solid #E6E6E6', background: active ? '#F26419' : '#fff', color: active ? '#fff' : '#5E5E5E', cursor: 'pointer' }}>
      {label}
    </button>
  )
}

export default function RecipeSearch() {
  const nav = useNavigate()
  // 필터 = URL 쿼리파라미터(q/ct/lv)로 승격 → 상세 진입 후 뒤로가기 시 복원.
  // (React Query 캐시가 같은 키 결과를 유지하므로 데이터도 즉시 복원됨)
  const [sp, setSp] = useSearchParams()
  const [q, setQ] = useState(() => sp.get('q') ?? '')
  const [dq, setDq] = useState(() => sp.get('q') ?? '') // 디바운스된(=확정) 검색어
  const [ct, setCt] = useState(() => sp.get('ct') ?? '') // 조리시간 태그 ('' = 전체)
  const [lv, setLv] = useState(() => sp.get('lv') ?? '') // 난이도 태그 ('' = 전체)
  const sentinel = useRef<HTMLDivElement>(null)

  // 300ms 디바운스 — 타이핑마다 요청하지 않도록
  useEffect(() => {
    const t = setTimeout(() => setDq(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])

  // 확정 검색어·필터를 URL에 반영(replace=히스토리 누적 방지). 뒤로가기로 돌아오면
  // 마운트 시 위 useState 초기화가 이 값을 다시 읽어 필터/검색어가 복원된다.
  useEffect(() => {
    const next = new URLSearchParams()
    if (dq) next.set('q', dq)
    if (ct) next.set('ct', ct)
    if (lv) next.set('lv', lv)
    setSp(next, { replace: true })
  }, [dq, ct, lv, setSp])

  // 검색어·필터 = 캐시 키. 필터 전환 시 이전 결과 유지(placeholderData).
  const { data, error, isLoading, hasNextPage, fetchNextPage, isFetchingNextPage } =
    useRecipeSearch(dq, { cooking_time: ct || undefined, level: lv || undefined })

  // 유저 발행 레시피를 카탈로그와 함께 노출(상단). 조리시간·난이도 필터가 걸리면
  // 유저 레시피엔 해당 속성이 없어 숨긴다(검색어만 있을 때/무필터일 때 노출).
  const { data: sharedData } = useSharedRecipes(dq)
  const shared = !ct && !lv ? sharedData?.recipes ?? [] : []

  const total = data?.pages[0]?.total ?? 0
  // 페이지 평탄화 + id 중복 제거
  const items = useMemo<RecipeCard[]>(() => {
    const seen = new Set<number>()
    const out: RecipeCard[] = []
    for (const p of data?.pages ?? [])
      for (const r of p.recipes)
        if (!seen.has(r.id)) {
          seen.add(r.id)
          out.push(r)
        }
    return out
  }, [data])

  // 바닥 sentinel 관찰 → 400px 전에 다음 페이지
  useEffect(() => {
    const el = sentinel.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) fetchNextPage()
      },
      { rootMargin: '400px' },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  return (
    <div>
      <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: '0 0 16px' }}>레시피</h1>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="레시피명, 재료로 검색…"
        style={{ width: '100%', maxWidth: 480, padding: '11px 14px', border: '1.5px solid #E6E6E6', background: '#fff', fontSize: 14, outline: 'none', marginBottom: 16 }}
      />
      {/* 실데이터 필터: 조리시간 · 난이도 */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: '#9A9A9A', width: 48, flexShrink: 0 }}>조리시간</span>
        <Chip label="전체" active={ct === ''} onClick={() => setCt('')} />
        {TIME_TAGS.map((t) => <Chip key={t} label={t} active={ct === t} onClick={() => setCt(t)} />)}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 20 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: '#9A9A9A', width: 48, flexShrink: 0 }}>난이도</span>
        <Chip label="전체" active={lv === ''} onClick={() => setLv('')} />
        {LEVEL_TAGS.map((t) => <Chip key={t} label={t} active={lv === t} onClick={() => setLv(t)} />)}
      </div>

      {/* 상태 라인: 총 건수 / 표시 개수 / 에러 */}
      <div style={{ fontSize: 12.5, color: error ? '#F04452' : '#9A9A9A', marginBottom: 12 }}>
        {error
          ? `검색 서버에 연결할 수 없어요 (${error.message})`
          : `총 ${total.toLocaleString('ko-KR')}개${dq ? ` · "${dq}"` : ''}${ct ? ` · ${ct}` : ''}${lv ? ` · ${lv}` : ''} · ${items.length.toLocaleString('ko-KR')}개 표시${shared.length ? ` · 유저 공유 ${shared.length}` : ''}`}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(190px,1fr))', gap: 16 }}>
        {/* 유저 발행 레시피 — 카탈로그와 한 그리드로 합류(상단), '유저 공유' 뱃지 */}
        {shared.map((s) => (
          <div key={`u-${s.id}`} onClick={() => nav('/shared/' + s.share_token)} className="zoom-wrap" style={{ background: '#fff', border: '1px solid #E6E6E6', cursor: 'pointer' }}>
            <div className="zoom" style={{ width: '100%', aspectRatio: '5/3', background: `#F0F0F0 center/cover no-repeat url("${s.image_url || DEFAULT_RECIPE_THUMB}")` }} />
            <div style={{ padding: 13 }}>
              <div style={{ marginBottom: 5 }}>
                <span style={{ fontSize: 10.5, fontWeight: 700, color: '#1B7A46', background: '#E7F5EC', padding: '2px 6px' }}>유저 공유</span>
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.title}</div>
              <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 4 }}>유저 공유 레시피</div>
            </div>
          </div>
        ))}
        {items.map((r) => {
          const meta = [r.cooking_time, r.level_nm].filter(Boolean).join(' · ')
          return (
            <div key={r.id} onClick={() => nav('/recipes/' + r.id)} className="zoom-wrap" style={{ background: '#fff', border: '1px solid #E6E6E6', cursor: 'pointer' }}>
              <div className="zoom" style={{ width: '100%', aspectRatio: '5/3', background: `#F0F0F0 center/cover no-repeat url("${r.image_url || img(r.id)}")` }} />
              <div style={{ padding: 13 }}>
                <div style={{ fontSize: 14, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</div>
                <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 4 }}>{meta || r.category || '만개의레시피'}</div>
              </div>
            </div>
          )
        })}
      </div>

      {/* 무한 스크롤 sentinel + 상태 */}
      <div ref={sentinel} style={{ height: 1 }} />
      <div style={{ textAlign: 'center', color: '#9A9A9A', fontSize: 13, padding: '20px 0 8px' }}>
        {isLoading || isFetchingNextPage ? '불러오는 중…' : !error && items.length === 0 && shared.length === 0 ? '검색 결과가 없어요.' : !hasNextPage && items.length > 0 ? '모든 레시피를 불러왔어요.' : ''}
      </div>
    </div>
  )
}
