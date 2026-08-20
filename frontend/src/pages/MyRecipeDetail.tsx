import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { DEFAULT_RECIPE_THUMB } from '../lib/data'
import { safeHttpUrl } from '../lib/url'
import type { Ingredient } from '../lib/api'
import { useAddCartItems, useDeleteMyRecipe, useMyRecipe, usePublishMyRecipe, useUnpublishMyRecipe } from '../lib/queries'
import AddToCartModal, { type CartPick } from '../components/AddToCartModal'
import ShareLinkModal from '../components/ShareLinkModal'
import RecipeDetailLayout from '../components/RecipeDetailLayout'

// 내가 직접 작성한 레시피 상세(#10 '보기'). 크롤링 상세(RecipeDetail)와 동일 공용 레이아웃 사용(#4 완전 통일).
// 유저 재료도 이름→item_id 매칭으로 최저가·영양·담기까지 만개 레시피와 동일하게 동작(단 미매칭 재료는 '-').
export default function MyRecipeDetail() {
  const nav = useNavigate()
  const { id } = useParams()
  const rid = Number(id)
  const { data, isLoading, error } = useMyRecipe(rid)
  const del = useDeleteMyRecipe()
  const publish = usePublishMyRecipe()
  const unpublish = useUnpublishMyRecipe()
  const addCart = useAddCartItems()
  const [share, setShare] = useState<string | null>(null)
  const [pick, setPick] = useState(false)

  const link = (token: string) => `${window.location.origin}/shared/${token}`
  const onShare = () => {
    if (!data) return
    if (data.is_public && data.share_token) { setShare(link(data.share_token)); return }
    publish.mutate(rid, { onSuccess: (info) => setShare(link(info.share_token)) })
  }
  const onUnpublish = () => {
    if (confirm('공개를 취소할까요? 레시피 목록에서 내려가요.')) unpublish.mutate(rid)
  }
  const onDelete = () => {
    if (data && confirm(`"${data.title}" 삭제할까요?`)) del.mutate(rid, { onSuccess: () => nav('/recipebook') })
  }
  const onConfirmCart = (picks: CartPick[]) => {
    // 유저 레시피는 public.recipe 카탈로그가 아니므로 recipe_id 는 null(장바구니는 재료만 담음).
    const items = picks.map((p) => ({ name: p.name, item_id: p.item_id, recipe_id: null, quantity: p.quantity, qty: 1 }))
    addCart.mutate(items, { onSuccess: () => { setPick(false); nav('/cart') } })
  }

  if (isLoading) return <div style={{ color: '#9A9A9A', padding: '40px 4px' }}>불러오는 중…</div>
  if (error || !data)
    return (
      <div style={{ padding: '40px 4px' }}>
        <div style={{ color: '#F04452', fontWeight: 700, marginBottom: 8 }}>레시피를 불러오지 못했어요</div>
        <div style={{ color: '#9A9A9A', fontSize: 13 }}>{error?.message ?? '데이터 없음'}</div>
        <button onClick={() => nav('/recipebook')} style={{ marginTop: 16, padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>← 내 레시피북</button>
      </div>
    )

  // 유저 재료(name·최저가·영양) → 담기 모달의 Ingredient shape.
  const cartIngredients: Ingredient[] = data.ingredients.map((g, i) => ({
    seq: i, ingredient_name: g.name, quantity: g.quantity, item_id: g.item_id, ner_status: '',
    lowest_source: g.lowest_source, lowest_krw_per_100g: g.lowest_krw_per_100g,
    kurly_krw_per_100g: g.kurly_krw_per_100g, oasis_krw_per_100g: g.oasis_krw_per_100g,
    // 🔴 이걸 빼면 모달이 상비양념을 **일반 재료로 본다** — 2026-08-19 실측에서 양념 오매칭
    //    18건이 그대로 «가격» 으로 노출되고 있었다(참기름→김 스낵, 설탕→냉동 제육볶음).
    excluded: g.excluded, cost_basis: g.cost_basis,
  }))

  // 유저가 넣은 원본 URL(source_url)은 http/https 만 렌더 — javascript: 등 스킴 클릭 시 스크립트 실행 차단.
  const sourceUrl = safeHttpUrl(data.source_url)

  return (
    <>
      <RecipeDetailLayout
        onBack={() => nav(-1)}
        breadcrumb={<><span style={{ cursor: 'pointer' }} onClick={() => nav('/recipebook')}>내 레시피북</span> / {data.title}</>}
        title={data.title}
        image={data.image_url || DEFAULT_RECIPE_THUMB}
        chips={[data.cooking_time, data.serving, data.level_nm].filter(Boolean) as string[]}
        steps={data.steps}
        ingredients={data.ingredients}
        onAddCart={() => setPick(true)}
        source={sourceUrl ? (
          <a href={sourceUrl} target="_blank" rel="noreferrer" style={{ color: '#F26419', textDecoration: 'none', fontWeight: 600 }}>📺 YouTube 원본 보기 →</a>
        ) : undefined}
        actions={
          // 만개(RecipeDetail) 헤더와 동일: 공유(회색 아웃라인) + 장바구니 담기(주황). 소유자 전용 관리는 하단으로.
          <>
            <button onClick={onShare} disabled={publish.isPending} style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
              {publish.isPending ? '공개 중…' : '공유'}
            </button>
            <button onClick={() => setPick(true)} style={{ padding: '9px 14px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>장바구니 담기</button>
          </>
        }
      />

      {/* 소유자 전용 관리 — 만개 레시피엔 없는 기능이라 레시피 본문과 분리해 하단에 조용히 배치(삭제는 레시피북 목록에도 있음). */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 18, marginTop: 20, paddingTop: 14, borderTop: '1px solid #EFEFEF' }}>
        {data.is_public && (
          <button onClick={onUnpublish} disabled={unpublish.isPending} style={{ background: 'none', border: 'none', color: '#9A9A9A', fontSize: 12.5, fontWeight: 700, cursor: 'pointer', textDecoration: 'underline', textUnderlineOffset: 3 }}>공개 취소</button>
        )}
        <button onClick={onDelete} disabled={del.isPending} style={{ background: 'none', border: 'none', color: '#C0392B', fontSize: 12.5, fontWeight: 700, cursor: 'pointer', textDecoration: 'underline', textUnderlineOffset: 3 }}>레시피 삭제</button>
      </div>

      <AddToCartModal
        open={pick}
        onClose={() => setPick(false)}
        recipeName={data.title}
        ingredients={cartIngredients}
        onConfirm={onConfirmCart}
        pending={addCart.isPending}
      />

      <ShareLinkModal
        open={!!share}
        onClose={() => setShare(null)}
        title="레시피 공유"
        heading={<><b style={{ color: '#17264A' }}>{data.title}</b> 을(를) 레시피 목록에 공개했어요. 이 링크로 누구나 열어볼 수 있어요.</>}
        link={share ?? ''}
      />
    </>
  )
}
