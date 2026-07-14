import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { recipeFilters, img } from '../lib/data'
import { searchRecipes } from '../lib/api'
import { useFetch } from '../lib/useFetch'

export default function RecipeSearch() {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('') // 디바운스된 검색어

  // 300ms 디바운스 — 타이핑마다 요청하지 않도록
  useEffect(() => {
    const t = setTimeout(() => setDq(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])

  const { data, error, loading } = useFetch(() => searchRecipes(dq, 1, 24), [dq])
  const recipes = data?.recipes ?? []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 16 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>레시피 탐색</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>직접 작성</button>
          <button style={{ padding: '9px 14px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }} onClick={() => nav('/youtube')}>YouTube로 추가</button>
        </div>
      </div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="레시피명, 재료로 검색…"
        style={{ width: '100%', maxWidth: 480, padding: '11px 14px', border: '1.5px solid #E6E6E6', background: '#fff', fontSize: 14, outline: 'none', marginBottom: 16 }}
      />
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 }}>
        {recipeFilters.map((f, i) => (
          <div key={f} style={{ padding: '7px 14px', fontSize: 13, fontWeight: i === 0 ? 700 : 600, border: i === 0 ? '1.5px solid #F26419' : '1.5px solid #E6E6E6', background: i === 0 ? '#F26419' : '#fff', color: i === 0 ? '#fff' : '#5E5E5E', cursor: 'pointer' }}>
            {f}
          </div>
        ))}
      </div>

      {/* 상태 라인: 총 건수 / 로딩 / 에러 */}
      <div style={{ fontSize: 12.5, color: error ? '#F04452' : '#9A9A9A', marginBottom: 12 }}>
        {error
          ? `검색 서버에 연결할 수 없어요 (${error})`
          : loading
            ? '불러오는 중…'
            : `총 ${data?.total?.toLocaleString('ko-KR') ?? 0}개${dq ? ` · "${dq}"` : ''}`}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(190px,1fr))', gap: 16 }}>
        {recipes.map((r, i) => {
          const meta = [r.cooking_time, r.level_nm, r.source].filter(Boolean).join(' · ')
          return (
            <div key={r.id} onClick={() => nav('/recipes/' + r.id)} style={{ background: '#fff', border: '1px solid #E6E6E6', overflow: 'hidden', cursor: 'pointer' }}>
              <div style={{ width: '100%', aspectRatio: '5/3', background: `#F0F0F0 center/cover no-repeat url("${r.image_url || img(i)}")` }} />
              <div style={{ padding: 13 }}>
                <div style={{ fontSize: 14, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</div>
                <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 4 }}>{meta || r.category || '만개의레시피'}</div>
              </div>
            </div>
          )
        })}
        {!loading && !error && recipes.length === 0 && (
          <div style={{ color: '#9A9A9A', fontSize: 14, padding: '20px 4px' }}>검색 결과가 없어요.</div>
        )}
      </div>
    </div>
  )
}
