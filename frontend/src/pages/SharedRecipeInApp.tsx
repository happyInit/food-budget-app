import { useNavigate, useParams } from 'react-router-dom'
import { useSharedRecipe } from '../lib/queries'
import { DEFAULT_RECIPE_THUMB } from '../lib/data'
import RecipeDetailLayout from '../components/RecipeDetailLayout'

// 발행된 유저 공유 레시피를 '앱 안에서' 열람하는 화면(#4 헤더 통일).
// 크롤(만개) 상세(RecipeDetail)와 완전히 동일한 헤더/레이아웃 — 뒤로·브레드크럼·제목·좌사진/우재료(최저가·영양).
// 외부 공개 링크(/shared/:token)는 별도 공개 chrome(SharedRecipe) 유지 — 인앱 진입만 이 화면으로.
export default function SharedRecipeInApp() {
  const nav = useNavigate()
  const { token } = useParams()
  const { data, isLoading, error } = useSharedRecipe(token ?? '')

  if (isLoading) return <div style={{ color: '#9A9A9A', padding: '40px 4px' }}>불러오는 중…</div>
  if (error || !data)
    return (
      <div style={{ padding: '40px 4px' }}>
        <div style={{ color: '#F04452', fontWeight: 700, marginBottom: 8 }}>레시피를 불러오지 못했어요</div>
        <div style={{ color: '#9A9A9A', fontSize: 13 }}>{(error as Error)?.message ?? '링크가 만료됐거나 비공개로 바뀌었을 수 있어요.'}</div>
        <button onClick={() => nav('/recipes')} style={{ marginTop: 16, padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>← 레시피 목록</button>
      </div>
    )

  return (
    <RecipeDetailLayout
      onBack={() => nav(-1)}
      breadcrumb={<><span style={{ cursor: 'pointer' }} onClick={() => nav('/recipes')}>레시피</span> / {data.title}</>}
      title={data.title}
      image={data.image_url || DEFAULT_RECIPE_THUMB}
      chips={[data.cooking_time, data.serving, data.level_nm].filter(Boolean) as string[]}
      steps={data.steps}
      ingredients={data.ingredients}
    />
  )
}
