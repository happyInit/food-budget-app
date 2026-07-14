import { useNavigate } from 'react-router-dom'
import { img } from '../lib/data'

const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }
const th: React.CSSProperties = { textAlign: 'left', padding: '7px 8px', borderBottom: '2px solid #E6E6E6', fontSize: 11.5, color: '#5E5E5E', fontWeight: 600 }
const td: React.CSSProperties = { padding: '10px 8px', borderBottom: '1px solid #EFEFEF' }

function stateChip(label: string, tone: 'have' | 'buy' | 'danger') {
  const c = tone === 'have' ? { bg: '#E7EFF8', fg: '#1E5F96' } : tone === 'danger' ? { bg: '#FDECEC', fg: '#F04452' } : { bg: '#FCEBDD', fg: '#F26419' }
  return <span style={{ padding: '2px 7px', fontSize: 11, background: c.bg, color: c.fg, fontWeight: 600 }}>{label}</span>
}

const ingredients = [
  { name: '김치 (묵은지)', qty: '200g', state: stateChip('보유', 'have'), price: '0원', owned: true },
  { name: '돼지고기 목살', qty: '150g', state: stateChip('구매', 'buy'), price: '2,950원', owned: false },
  { name: '두부', qty: '1/2모', state: stateChip('D-1', 'danger'), price: '0원', owned: true },
  { name: '대파', qty: '1대', state: stateChip('구매', 'buy'), price: '1,250원', owned: false },
]
const steps = [
  '묵은지를 먹기 좋게 썰고 돼지고기와 함께 냄비에 볶는다.',
  '물 2컵을 붓고 고춧가루·다진마늘을 넣어 끓인다.',
  '두부와 대파를 넣고 5분 더 끓이면 완성.',
]
const nutri = [
  { k: '칼로리', w: 45, c: '#F26419', v: '312 kcal' },
  { k: '단백질', w: 62, c: '#1E5F96', v: '24g' },
  { k: '탄수화물', w: 30, c: '#F26419', v: '18g' },
  { k: '지방', w: 38, c: '#F26419', v: '16g' },
  { k: '나트륨', w: 55, c: '#F04452', v: '980mg' },
]

export default function RecipeDetail() {
  const nav = useNavigate()
  return (
    <div>
      <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 10 }}>
        <span style={{ cursor: 'pointer' }} onClick={() => nav('/recipes')}>레시피</span> / 김치찌개
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>김치찌개</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={{ padding: '9px 14px', border: '1.5px solid #F26419', background: '#fff', color: '#F26419', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>레시피북 저장</button>
          <button onClick={() => nav('/cart')} style={{ padding: '9px 14px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>장바구니 담기</button>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 16 }}>
        {/* 좌: 사진 + 조리순서 */}
        <div>
          <img src={img(0, 640)} style={{ width: '100%', aspectRatio: '16/10', objectFit: 'cover', display: 'block', background: '#F0F0F0' }} />
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
            {['30분', '1인분', '4.7 (2.3k)', '만개의레시피'].map((t, i) => (
              <span key={t} style={{ padding: '4px 10px', fontSize: 11.5, fontWeight: 700, background: i === 1 ? '#E7EFF8' : '#FCEBDD', color: i === 1 ? '#1E5F96' : '#F26419' }}>{t}</span>
            ))}
          </div>
          <div style={{ ...card, marginTop: 16 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>조리 순서</h3>
            {steps.map((s, i) => (
              <div key={i} style={{ display: 'flex', gap: 12, padding: '10px 0', fontSize: 13.5, lineHeight: 1.6, borderTop: i > 0 ? '1px solid #EFEFEF' : 'none' }}>
                <span style={{ flexShrink: 0, width: 22, height: 22, borderRadius: '50%', background: '#FCEBDD', color: '#F26419', fontWeight: 700, fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{i + 1}</span>
                {s}
              </div>
            ))}
          </div>
        </div>
        {/* 우: 가격표 + 영양 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0 }}>재료 + 마켓컬리 가격</h3>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#5E5E5E' }}>
                인분
                <button style={{ width: 22, height: 22, border: '1px solid #E6E6E6', background: '#fff', cursor: 'pointer' }}>−</button>
                <b className="num">1</b>
                <button style={{ width: 22, height: 22, border: '1px solid #E6E6E6', background: '#fff', cursor: 'pointer' }}>+</button>
              </div>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={th}>재료</th>
                    <th style={th}>수량</th>
                    <th style={th}>상태</th>
                    <th style={{ ...th, textAlign: 'right' }}>가격</th>
                  </tr>
                </thead>
                <tbody>
                  {ingredients.map((g, i) => (
                    <tr key={i}>
                      <td style={i === ingredients.length - 1 ? { padding: '10px 8px' } : td}>{g.name}</td>
                      <td style={i === ingredients.length - 1 ? { padding: '10px 8px' } : td}>{g.qty}</td>
                      <td style={i === ingredients.length - 1 ? { padding: '10px 8px' } : td}>{g.state}</td>
                      <td className="num" style={{ ...(i === ingredients.length - 1 ? { padding: '10px 8px' } : td), textAlign: 'right', fontWeight: g.owned ? 400 : 700, color: g.owned ? '#9A9A9A' : '#17264A', textDecoration: g.owned ? 'line-through' : 'none' }}>{g.price}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ marginTop: 14, padding: '14px 16px', background: '#FCEBDD', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 12, color: '#F26419' }}>추가 구매 비용</div>
                <div className="num" style={{ fontSize: 20, fontWeight: 800, color: '#F26419' }}>4,200원</div>
              </div>
              <button onClick={() => nav('/cart')} style={{ padding: '10px 16px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>담기</button>
            </div>
          </div>
          <div style={card}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>영양성분 (1인분)</h3>
            {nutri.map((n) => (
              <div key={n.k} style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '7px 0' }}>
                <span style={{ fontSize: 12, color: '#5E5E5E', width: 52 }}>{n.k}</span>
                <div style={{ flex: 1, height: 7, background: '#EFEFEF', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: n.w + '%', background: n.c }} />
                </div>
                <span className="num" style={{ fontSize: 12, color: '#5E5E5E', width: 58, textAlign: 'right' }}>{n.v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
