import { type ReactNode } from 'react'
import IngredientPanels from './IngredientPanels'
import type { UserRecipeIngredient } from '../lib/api'

// 레시피 상세 공용 레이아웃 — 크롤링(RecipeDetail)·유저작성(MyRecipeDetail)·공유뷰(SharedRecipe)가
// 완전히 동일한 UI를 쓰도록 뼈대를 한 곳에. 좌=사진+칩+조리순서 / 우=재료 최저가·영양(IngredientPanels).
// 컨텍스트별로 다른 것만 슬롯으로: breadcrumb·badges·actions·onAddCart.
const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }

export default function RecipeDetailLayout({
  onBack, breadcrumb, badges, title, actions, image, chips, steps, ingredients, onAddCart, reviews,
}: {
  onBack?: () => void
  breadcrumb?: ReactNode          // 인증 컨텍스트만(공개 공유뷰는 생략)
  badges?: ReactNode
  title: string
  actions?: ReactNode             // 컨텍스트별 버튼(공개 공유뷰는 없음)
  image: string
  chips: string[]
  steps: string[]
  ingredients: UserRecipeIngredient[]
  onAddCart?: () => void
  reviews?: ReactNode             // #10 후기 요약(있을 때만 — 크롤링 레시피 전용, 유저작성엔 없음)
}) {
  return (
    <div>
      {onBack && (
        <button
          onClick={onBack}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 10, padding: '6px 12px 6px 8px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}
        >
          ← 뒤로
        </button>
      )}
      {breadcrumb && <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 10 }}>{breadcrumb}</div>}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {badges}
          <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>{title}</h1>
        </div>
        {actions && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{actions}</div>}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 16 }}>
        {/* 좌: 사진 + 칩 + 조리순서 */}
        <div>
          <div className="zoom-wrap">
            <img src={image} style={{ width: '100%', aspectRatio: '16/10', objectFit: 'cover', display: 'block', background: '#F0F0F0' }} />
          </div>
          {chips.length > 0 && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
              {chips.map((t, i) => (
                <span key={t + i} style={{ padding: '4px 10px', fontSize: 11.5, fontWeight: 700, background: i === 1 ? '#E7EFF8' : '#FCEBDD', color: i === 1 ? '#1E5F96' : '#F26419' }}>{t}</span>
              ))}
            </div>
          )}
          <div style={{ ...card, marginTop: 16 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>조리 순서</h3>
            {steps.length === 0 && <div style={{ color: '#9A9A9A', fontSize: 13 }}>조리 순서 정보가 없어요.</div>}
            {steps.map((s, i) => (
              <div key={i} style={{ display: 'flex', gap: 12, padding: '10px 0', fontSize: 13.5, lineHeight: 1.6, borderTop: i > 0 ? '1px solid #EFEFEF' : 'none' }}>
                <span style={{ flexShrink: 0, width: 22, height: 22, borderRadius: '50%', background: '#FCEBDD', color: '#F26419', fontWeight: 700, fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{i + 1}</span>
                {s}
              </div>
            ))}
          </div>
        </div>
        {/* 우: 재료 최저가 + 영양 */}
        <IngredientPanels ingredients={ingredients} onAddCart={onAddCart} />
      </div>

      {/* #10 후기 요약 — 그리드 아래 전체폭(레시피 전반 평가라 넓게) */}
      {reviews}
    </div>
  )
}
