import { useNavigate, useParams } from 'react-router-dom'
import { img } from '../lib/data'
import { getRecipe, won, type Ingredient } from '../lib/api'
import { useFetch } from '../lib/useFetch'

const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }
const th: React.CSSProperties = { textAlign: 'left', padding: '7px 8px', borderBottom: '2px solid #E6E6E6', fontSize: 11.5, color: '#5E5E5E', fontWeight: 600 }
const td: React.CSSProperties = { padding: '10px 8px', borderBottom: '1px solid #EFEFEF' }

const SRC_LABEL: Record<string, string> = { kurly: '컬리', oasis: '오아시스' }

function priceChip(ing: Ingredient) {
  if (ing.lowest_krw_per_100g != null) {
    const src = SRC_LABEL[ing.lowest_source ?? ''] ?? ing.lowest_source ?? '시세'
    return <span style={{ padding: '2px 7px', fontSize: 11, background: '#FCEBDD', color: '#F26419', fontWeight: 600 }}>{src}</span>
  }
  return <span style={{ padding: '2px 7px', fontSize: 11, background: '#F0F0F0', color: '#9A9A9A', fontWeight: 600 }}>미매칭</span>
}

// 영양 막대 폭: 참고치 대비 %(시각용), 0~100 클램프
const bar = (v: number | null | undefined, ref: number) => (v == null ? 0 : Math.min(100, Math.round((v / ref) * 100)))

export default function RecipeDetail() {
  const nav = useNavigate()
  const { id } = useParams()
  const { data, error, loading } = useFetch(() => getRecipe(Number(id)), [id])

  if (loading) return <div style={{ color: '#9A9A9A', padding: '40px 4px' }}>불러오는 중…</div>
  if (error || !data)
    return (
      <div style={{ padding: '40px 4px' }}>
        <div style={{ color: '#F04452', fontWeight: 700, marginBottom: 8 }}>레시피를 불러오지 못했어요</div>
        <div style={{ color: '#9A9A9A', fontSize: 13 }}>{error ?? '데이터 없음'}</div>
        <button onClick={() => nav('/recipes')} style={{ marginTop: 16, padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>← 레시피 목록</button>
      </div>
    )

  const n = data.nutrition ?? {}
  const matched = data.ingredients.filter((g) => g.lowest_krw_per_100g != null)
  const sum100g = matched.reduce((a, g) => a + (g.lowest_krw_per_100g ?? 0), 0)
  const chips = [data.cooking_time, data.serving, data.level_nm, data.source].filter(Boolean) as string[]

  const nutri = [
    { k: '칼로리', c: '#F26419', w: bar(n.kcal, 900), v: n.kcal != null ? `${Math.round(n.kcal)} kcal` : '-' },
    { k: '단백질', c: '#1E5F96', w: bar(n.protein_g, 50), v: n.protein_g != null ? `${Math.round(n.protein_g)}g` : '-' },
    { k: '탄수화물', c: '#F26419', w: bar(n.carb_g, 100), v: n.carb_g != null ? `${Math.round(n.carb_g)}g` : '-' },
    { k: '지방', c: '#F26419', w: bar(n.fat_g, 50), v: n.fat_g != null ? `${Math.round(n.fat_g)}g` : '-' },
    { k: '나트륨', c: '#F04452', w: bar(n.sodium_mg, 2000), v: n.sodium_mg != null ? `${Math.round(n.sodium_mg)}mg` : '-' },
  ]

  return (
    <div>
      <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 10 }}>
        <span style={{ cursor: 'pointer' }} onClick={() => nav('/recipes')}>레시피</span> / {data.name}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>{data.name}</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={{ padding: '9px 14px', border: '1.5px solid #F26419', background: '#fff', color: '#F26419', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>레시피북 저장</button>
          <button onClick={() => nav('/cart')} style={{ padding: '9px 14px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>장바구니 담기</button>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 16 }}>
        {/* 좌: 사진 + 조리순서 */}
        <div>
          <img src={data.image_url || img(data.id, 640)} style={{ width: '100%', aspectRatio: '16/10', objectFit: 'cover', display: 'block', background: '#F0F0F0' }} />
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
            {chips.map((t, i) => (
              <span key={t + i} style={{ padding: '4px 10px', fontSize: 11.5, fontWeight: 700, background: i === 1 ? '#E7EFF8' : '#FCEBDD', color: i === 1 ? '#1E5F96' : '#F26419' }}>{t}</span>
            ))}
          </div>
          <div style={{ ...card, marginTop: 16 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>조리 순서</h3>
            {data.steps.length === 0 && <div style={{ color: '#9A9A9A', fontSize: 13 }}>조리 순서 정보가 없어요.</div>}
            {data.steps.map((s, i) => (
              <div key={s.step_no} style={{ display: 'flex', gap: 12, padding: '10px 0', fontSize: 13.5, lineHeight: 1.6, borderTop: i > 0 ? '1px solid #EFEFEF' : 'none' }}>
                <span style={{ flexShrink: 0, width: 22, height: 22, borderRadius: '50%', background: '#FCEBDD', color: '#F26419', fontWeight: 700, fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{s.step_no}</span>
                {s.description}
              </div>
            ))}
          </div>
        </div>
        {/* 우: 재료 최저가 + 영양 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0 }}>재료 · 실시간 최저가</h3>
              <span style={{ fontSize: 11.5, color: '#9A9A9A' }}>컬리·오아시스 100g 환산</span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={th}>재료</th>
                    <th style={th}>수량</th>
                    <th style={th}>출처</th>
                    <th style={{ ...th, textAlign: 'right' }}>최저가(100g)</th>
                  </tr>
                </thead>
                <tbody>
                  {data.ingredients.map((g, i) => {
                    const last = i === data.ingredients.length - 1
                    const cell = last ? { padding: '10px 8px' } : td
                    const has = g.lowest_krw_per_100g != null
                    return (
                      <tr key={g.seq ?? i}>
                        <td style={cell}>{g.ingredient_name}</td>
                        <td style={cell}>{g.quantity || '-'}</td>
                        <td style={cell}>{priceChip(g)}</td>
                        <td className="num" style={{ ...cell, textAlign: 'right', fontWeight: has ? 700 : 400, color: has ? '#17264A' : '#B5B5B5' }}>
                          {has ? `${won(g.lowest_krw_per_100g)}원` : '-'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ marginTop: 14, padding: '14px 16px', background: '#FCEBDD', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 12, color: '#F26419' }}>가격 확인된 재료 {matched.length}/{data.ingredients.length}개 · 100g 최저가 합</div>
                <div className="num" style={{ fontSize: 20, fontWeight: 800, color: '#F26419' }}>{won(sum100g)}원</div>
              </div>
              <button onClick={() => nav('/cart')} style={{ padding: '10px 16px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>담기</button>
            </div>
          </div>
          <div style={card}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>영양성분 {data.serving ? `(${data.serving})` : ''}</h3>
            {nutri.map((x) => (
              <div key={x.k} style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '7px 0' }}>
                <span style={{ fontSize: 12, color: '#5E5E5E', width: 52 }}>{x.k}</span>
                <div style={{ flex: 1, height: 7, background: '#EFEFEF', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: x.w + '%', background: x.c }} />
                </div>
                <span className="num" style={{ fontSize: 12, color: '#5E5E5E', width: 62, textAlign: 'right' }}>{x.v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
