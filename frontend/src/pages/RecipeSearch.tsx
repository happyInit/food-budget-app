import { useNavigate } from 'react-router-dom'
import { recipeList, recipeFilters, img } from '../lib/data'

export default function RecipeSearch() {
  const nav = useNavigate()
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 16 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>레시피 탐색</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>직접 작성</button>
          <button style={{ padding: '9px 14px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }} onClick={() => nav('/youtube')}>YouTube로 추가</button>
        </div>
      </div>
      <input placeholder="레시피명, 재료로 검색…" style={{ width: '100%', maxWidth: 480, padding: '11px 14px', border: '1.5px solid #E6E6E6', background: '#fff', fontSize: 14, outline: 'none', marginBottom: 16 }} />
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 }}>
        {recipeFilters.map((f, i) => (
          <div key={f} style={{ padding: '7px 14px', fontSize: 13, fontWeight: i === 0 ? 700 : 600, border: i === 0 ? '1.5px solid #F26419' : '1.5px solid #E6E6E6', background: i === 0 ? '#F26419' : '#fff', color: i === 0 ? '#fff' : '#5E5E5E', cursor: 'pointer' }}>
            {f}
          </div>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(190px,1fr))', gap: 16 }}>
        {recipeList.map((r, i) => (
          <div key={r.name} onClick={() => nav('/recipes/' + (i + 1))} style={{ background: '#fff', border: '1px solid #E6E6E6', overflow: 'hidden', cursor: 'pointer' }}>
            <div style={{ width: '100%', aspectRatio: '5/3', background: `#F0F0F0 center/cover no-repeat url("${img(i)}")` }} />
            <div style={{ padding: 13 }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{r.name}</div>
              <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 4 }}>{r.meta}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
