import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { img } from '../lib/data'
import type { UserRecipeIngredient } from '../lib/api'
import { useAddBookmark, useAddCartItems, useBookmarks, useRecipe, useRecipeReviews } from '../lib/queries'
import AddToCartModal, { type CartPick } from '../components/AddToCartModal'
import ShareLinkModal from '../components/ShareLinkModal'
import RecipeDetailLayout from '../components/RecipeDetailLayout'
import ReviewSummaryCard from '../components/ReviewSummaryCard'

export default function RecipeDetail() {
  const nav = useNavigate()
  const { id } = useParams()
  const [pick, setPick] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const { data, error, isLoading } = useRecipe(Number(id))
  const { data: reviews } = useRecipeReviews(Number(id))   // #10 후기 요약(없으면 undefined → 섹션 숨김)
  const addBookmark = useAddBookmark()
  const addCart = useAddCartItems()
  const { data: bookmarks } = useBookmarks()
  const [savedLocal, setSavedLocal] = useState(false)
  // 이미 레시피북에 담긴 레시피면 버튼을 '저장됨'으로 초기화 → 중복 등록 방지(A: 서버도 409로 막음).
  const saved = savedLocal || !!bookmarks?.books.some((b) => b.recipe_id === Number(id))

  const onSaveBookmark = () => {
    if (!data || saved) return
    addBookmark.mutate(data.id, {
      onSuccess: () => setSavedLocal(true),
      // 이미 담긴 레시피(409)면 저장된 것으로 간주
      onError: (e) => e.message.startsWith('409') && setSavedLocal(true),
    })
  }

  const onConfirmCart = (picks: CartPick[]) => {
    if (!data) return
    const items = picks.map((p) => ({
      name: p.name,
      item_id: p.item_id,
      recipe_id: data.id,
      quantity: p.quantity,
      qty: 1,
    }))
    addCart.mutate(items, { onSuccess: () => { setPick(false); nav('/cart') } })
  }

  if (isLoading) return <div style={{ color: '#9A9A9A', padding: '40px 4px' }}>불러오는 중…</div>
  if (error || !data)
    return (
      <div style={{ padding: '40px 4px' }}>
        <div style={{ color: '#F04452', fontWeight: 700, marginBottom: 8 }}>레시피를 불러오지 못했어요</div>
        <div style={{ color: '#9A9A9A', fontSize: 13 }}>{error?.message ?? '데이터 없음'}</div>
        <button onClick={() => nav('/recipes')} style={{ marginTop: 16, padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>← 레시피 목록</button>
      </div>
    )

  const chips = [data.cooking_time, data.serving, data.level_nm].filter(Boolean) as string[]
  // recipe 서비스 Ingredient → 공용 패널 재료 shape(이름 필드만 다름).
  const panelIngredients: UserRecipeIngredient[] = data.ingredients.map((g) => ({
    name: g.ingredient_name ?? '', quantity: g.quantity, item_id: g.item_id,
    lowest_source: g.lowest_source, lowest_krw_per_100g: g.lowest_krw_per_100g,
    kurly_krw_per_100g: g.kurly_krw_per_100g, oasis_krw_per_100g: g.oasis_krw_per_100g,
    kcal_100g: g.kcal_100g, protein_100g: g.protein_100g, carb_100g: g.carb_100g,
    fat_100g: g.fat_100g, sodium_100g: g.sodium_100g,
    usage_grams: g.usage_grams, usage_krw: g.usage_krw, cost_basis: g.cost_basis,
  }))

  return (
    <>
      <RecipeDetailLayout
        onBack={() => nav(-1)}
        breadcrumb={<><span style={{ cursor: 'pointer' }} onClick={() => nav('/recipes')}>레시피</span> / {data.name}</>}
        title={data.name}
        image={data.image_url || img(data.id, 640)}
        chips={chips}
        steps={data.steps.map((s) => s.description ?? '')}
        ingredients={panelIngredients}
        onAddCart={() => setPick(true)}
        reviews={reviews ? <ReviewSummaryCard data={reviews} /> : undefined}
        actions={
          <>
            <button onClick={() => setShareOpen(true)} style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>공유</button>
            <button
              onClick={onSaveBookmark}
              disabled={saved || addBookmark.isPending}
              style={{ padding: '9px 14px', border: '1.5px solid #F26419', background: saved ? '#FCEBDD' : '#fff', color: '#F26419', fontSize: 13, fontWeight: 700, cursor: saved ? 'default' : 'pointer' }}
            >
              {saved ? '레시피북 저장됨 ✓' : addBookmark.isPending ? '저장 중…' : '레시피북 저장'}
            </button>
            <button onClick={() => setPick(true)} style={{ padding: '9px 14px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>장바구니 담기</button>
          </>
        }
      />

      <AddToCartModal
        open={pick}
        onClose={() => setPick(false)}
        recipeName={data.name}
        ingredients={data.ingredients}
        onConfirm={onConfirmCart}
        pending={addCart.isPending}
      />

      <ShareLinkModal
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        title="레시피 공유"
        heading={<><b style={{ color: '#17264A' }}>{data.name}</b> 레시피 링크예요. 복사해서 공유하거나 새 탭에서 열어보세요.</>}
        link={`${window.location.origin}/recipes/${data.id}`}
      />
    </>
  )
}
