import { useParams, useNavigate } from 'react-router-dom'
import { useSharedRecipe } from '../lib/queries'
import { DEFAULT_RECIPE_THUMB } from '../lib/data'
import RecipeDetailLayout from '../components/RecipeDetailLayout'

// 공개 공유 뷰 — 로그인 없이 링크(/shared/:token)로 열람. AppShell 밖 독립 페이지.
// 본문은 크롤링·유저 상세와 동일한 공용 레이아웃(RecipeDetailLayout) — 공개뷰라 액션·담기·뒤로가기는 생략.
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

      <div style={{ maxWidth: 900, margin: '0 auto', padding: '24px 20px 48px' }}>
        {isLoading && <div style={{ color: '#9A9A9A', padding: '40px 0' }}>불러오는 중…</div>}

        {error && (
          <div style={{ textAlign: 'center', padding: '56px 20px', background: '#fff', border: '1px solid #EFEFEF' }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#17264A', marginBottom: 6 }}>레시피를 찾을 수 없어요</div>
            <div style={{ fontSize: 13, color: '#9A9A9A' }}>링크가 만료됐거나 비공개로 바뀌었을 수 있어요.</div>
          </div>
        )}

        {data && (
          <RecipeDetailLayout
            badges={<span style={{ fontSize: 10.5, fontWeight: 700, color: '#F26419', background: '#FCEBDD', padding: '3px 8px' }}>공유된 레시피</span>}
            title={data.title}
            image={data.image_url || DEFAULT_RECIPE_THUMB}
            chips={[]}
            steps={data.steps}
            ingredients={data.ingredients}
          />
        )}
      </div>
    </div>
  )
}
