import { useParams, useNavigate } from 'react-router-dom'
import { useSharedRecipe } from '../lib/queries'
import { DEFAULT_RECIPE_THUMB } from '../lib/data'
import IngredientPanels from '../components/IngredientPanels'

const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }

// 공개 공유 뷰 — 로그인 없이 링크(/shared/:token)로 열람. AppShell 밖 독립 페이지.
export default function SharedRecipe() {
  const nav = useNavigate()
  const { token } = useParams()
  const { data, isLoading, error } = useSharedRecipe(token ?? '')

  return (
    <div style={{ minHeight: '100vh', background: '#FAFAFA' }}>
      <div style={{ borderBottom: '1px solid #EFEFEF', background: '#fff' }}>
        <div style={{ maxWidth: 720, margin: '0 auto', padding: '14px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 16, fontWeight: 800, color: '#F26419', cursor: 'pointer' }} onClick={() => nav('/')}>냉장고 요리사</div>
          <button onClick={() => nav('/home')} style={{ padding: '7px 14px', border: '1.5px solid #F26419', background: '#fff', color: '#F26419', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>앱에서 더보기 →</button>
        </div>
      </div>

      <div style={{ maxWidth: 720, margin: '0 auto', padding: '24px 20px 48px' }}>
        {isLoading && <div style={{ color: '#9A9A9A', padding: '40px 0' }}>불러오는 중…</div>}

        {error && (
          <div style={{ textAlign: 'center', padding: '56px 20px', background: '#fff', border: '1px solid #EFEFEF' }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#17264A', marginBottom: 6 }}>레시피를 찾을 수 없어요</div>
            <div style={{ fontSize: 13, color: '#9A9A9A' }}>링크가 만료됐거나 비공개로 바뀌었을 수 있어요.</div>
          </div>
        )}

        {data && (
          <div>
            <div style={{ fontSize: 12, color: '#F26419', fontWeight: 700, marginBottom: 6 }}>공유된 레시피</div>
            <h1 style={{ fontSize: 24, fontWeight: 800, letterSpacing: '-.5px', margin: '0 0 18px' }}>{data.title}</h1>

            {/* 크롤링 레시피 상세(RecipeDetail)와 동일 레이아웃 — 좌 사진+조리순서 / 우 재료. */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 16 }}>
              <div>
                <img src={data.image_url || DEFAULT_RECIPE_THUMB} style={{ width: '100%', aspectRatio: '16/10', objectFit: 'cover', display: 'block', background: '#F0F0F0' }} />
                <div style={{ ...card, marginTop: 16 }}>
                  <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>조리 순서</h3>
                  {data.steps.length === 0 ? (
                    <div style={{ fontSize: 13, color: '#9A9A9A' }}>조리 순서 정보가 없어요.</div>
                  ) : (
                    data.steps.map((s, i) => (
                      <div key={i} style={{ display: 'flex', gap: 12, padding: '10px 0', fontSize: 13.5, lineHeight: 1.6, borderTop: i > 0 ? '1px solid #EFEFEF' : 'none' }}>
                        <span style={{ flexShrink: 0, width: 22, height: 22, borderRadius: '50%', background: '#FCEBDD', color: '#F26419', fontWeight: 700, fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{i + 1}</span>
                        <span>{s}</span>
                      </div>
                    ))
                  )}
                </div>
              </div>
              <div>
                {data.ingredients.length === 0 ? (
                  <div style={card}>
                    <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>재료</h3>
                    <div style={{ fontSize: 13, color: '#9A9A9A' }}>재료 정보가 없어요.</div>
                  </div>
                ) : (
                  <IngredientPanels ingredients={data.ingredients} />
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
