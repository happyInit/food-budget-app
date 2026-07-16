import { useParams, useNavigate } from 'react-router-dom'
import { useSharedRecipe } from '../lib/queries'
import { img } from '../lib/data'

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
          <div style={{ background: '#fff', border: '1px solid #E6E6E6' }}>
            <div style={{ height: 200, background: `#F0F0F0 center/cover no-repeat url("${data.image_url || img(token?.length ?? 1, 720)}")` }} />
            <div style={{ padding: '22px 24px 28px' }}>
              <div style={{ fontSize: 12, color: '#F26419', fontWeight: 700, marginBottom: 6 }}>공유된 레시피</div>
              <h1 style={{ fontSize: 24, fontWeight: 800, letterSpacing: '-.5px', margin: '0 0 20px' }}>{data.title}</h1>

              <h2 style={{ fontSize: 15, fontWeight: 800, color: '#17264A', margin: '0 0 10px' }}>재료</h2>
              {data.ingredients.length === 0 ? (
                <div style={{ fontSize: 13, color: '#9A9A9A', marginBottom: 20 }}>재료 정보가 없어요.</div>
              ) : (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 24 }}>
                  {data.ingredients.map((g, i) => (
                    <span key={i} style={{ padding: '6px 12px', background: '#FCEBDD', color: '#17264A', fontSize: 13, fontWeight: 600 }}>
                      {g.name}{g.quantity ? <span style={{ color: '#9A5A2A', marginLeft: 6 }}>{g.quantity}</span> : null}
                    </span>
                  ))}
                </div>
              )}

              <h2 style={{ fontSize: 15, fontWeight: 800, color: '#17264A', margin: '0 0 10px' }}>조리 순서</h2>
              {data.steps.length === 0 ? (
                <div style={{ fontSize: 13, color: '#9A9A9A' }}>조리 순서 정보가 없어요.</div>
              ) : (
                <div>
                  {data.steps.map((s, i) => (
                    <div key={i} style={{ display: 'flex', gap: 12, padding: '11px 0', fontSize: 14, lineHeight: 1.6, borderTop: i > 0 ? '1px solid #EFEFEF' : 'none' }}>
                      <span style={{ flexShrink: 0, width: 24, height: 24, borderRadius: '50%', background: '#FCEBDD', color: '#F26419', fontWeight: 700, fontSize: 12.5, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{i + 1}</span>
                      <span>{s}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
