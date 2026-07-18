import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { DEFAULT_RECIPE_THUMB } from '../lib/data'
import type { Ingredient } from '../lib/api'
import { useAddCartItems, useCreateMyRecipe, useSharedRecipe } from '../lib/queries'
import AddToCartModal, { type CartPick } from '../components/AddToCartModal'
import ShareLinkModal from '../components/ShareLinkModal'
import RecipeDetailLayout from '../components/RecipeDetailLayout'

// 발행된 유저 공유 레시피를 '앱 안에서' 열람(#4 헤더 통일 + #2 만개와 동일 액션).
// 크롤(만개) 상세와 완전히 동일한 헤더/레이아웃 + [공유][레시피북 저장][장바구니 담기].
// 외부 공개 링크(/shared/:token)는 별도 공개 chrome(SharedRecipe) 유지 — 인앱 진입만 이 화면.
export default function SharedRecipeInApp() {
  const nav = useNavigate()
  const { token } = useParams()
  const { data, isLoading, error } = useSharedRecipe(token ?? '')
  const addCart = useAddCartItems()
  const saveMine = useCreateMyRecipe()
  const [pick, setPick] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [saved, setSaved] = useState(false)

  const onConfirmCart = (picks: CartPick[]) => {
    // 공유 레시피는 카탈로그(public.recipe)가 아니므로 recipe_id 는 null — 재료만 담음.
    const items = picks.map((p) => ({ name: p.name, item_id: p.item_id, recipe_id: null, quantity: p.quantity, qty: 1 }))
    addCart.mutate(items, { onSuccess: () => { setPick(false); nav('/cart') } })
  }
  // '레시피북 저장' = 이 공유 레시피를 내 레시피북으로 복사(직접작성 MANUAL 사본 생성).
  const onSaveMine = () => {
    if (!data || saved || saveMine.isPending) return
    saveMine.mutate(
      {
        title: data.title,
        ingredients: data.ingredients.map((g) => ({ name: g.name, quantity: g.quantity })),
        steps: data.steps,
        image_url: data.image_url ?? undefined,
        cooking_time: data.cooking_time ?? undefined,
        serving: data.serving ?? undefined,
        level_nm: data.level_nm ?? undefined,
      },
      { onSuccess: () => setSaved(true) },
    )
  }

  if (isLoading) return <div style={{ color: '#9A9A9A', padding: '40px 4px' }}>불러오는 중…</div>
  if (error || !data)
    return (
      <div style={{ padding: '40px 4px' }}>
        <div style={{ color: '#F04452', fontWeight: 700, marginBottom: 8 }}>레시피를 불러오지 못했어요</div>
        <div style={{ color: '#9A9A9A', fontSize: 13 }}>{(error as Error)?.message ?? '링크가 만료됐거나 비공개로 바뀌었을 수 있어요.'}</div>
        <button onClick={() => nav('/recipes')} style={{ marginTop: 16, padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>← 레시피 목록</button>
      </div>
    )

  // 공유 재료(name·최저가·영양) → 담기 모달의 Ingredient shape.
  const cartIngredients: Ingredient[] = data.ingredients.map((g, i) => ({
    seq: i, ingredient_name: g.name, quantity: g.quantity, item_id: g.item_id, ner_status: '',
    lowest_source: g.lowest_source, lowest_krw_per_100g: g.lowest_krw_per_100g,
    kurly_krw_per_100g: g.kurly_krw_per_100g, oasis_krw_per_100g: g.oasis_krw_per_100g,
  }))

  return (
    <>
      <RecipeDetailLayout
        onBack={() => nav(-1)}
        breadcrumb={<><span style={{ cursor: 'pointer' }} onClick={() => nav('/recipes')}>레시피</span> / {data.title}</>}
        title={data.title}
        image={data.image_url || DEFAULT_RECIPE_THUMB}
        chips={[data.cooking_time, data.serving, data.level_nm].filter(Boolean) as string[]}
        steps={data.steps}
        ingredients={data.ingredients}
        onAddCart={() => setPick(true)}
        actions={
          // 만개(RecipeDetail) 헤더와 동일: 공유(회색) + 레시피북 저장(주황 아웃라인) + 장바구니 담기(주황).
          <>
            <button onClick={() => setShareOpen(true)} style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>공유</button>
            <button
              onClick={onSaveMine}
              disabled={saved || saveMine.isPending}
              style={{ padding: '9px 14px', border: '1.5px solid #F26419', background: saved ? '#FCEBDD' : '#fff', color: '#F26419', fontSize: 13, fontWeight: 700, cursor: saved ? 'default' : 'pointer' }}
            >
              {saved ? '레시피북 저장됨 ✓' : saveMine.isPending ? '저장 중…' : '레시피북 저장'}
            </button>
            <button onClick={() => setPick(true)} style={{ padding: '9px 14px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>장바구니 담기</button>
          </>
        }
      />

      <AddToCartModal
        open={pick}
        onClose={() => setPick(false)}
        recipeName={data.title}
        ingredients={cartIngredients}
        onConfirm={onConfirmCart}
        pending={addCart.isPending}
      />

      <ShareLinkModal
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        title="레시피 공유"
        heading={<><b style={{ color: '#17264A' }}>{data.title}</b> 레시피 링크예요. 복사해서 공유하거나 새 탭에서 열어보세요.</>}
        link={`${window.location.origin}/shared/${token}`}
      />
    </>
  )
}
