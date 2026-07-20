import { won } from '../lib/api'
import { SRC_LABEL, PRICE_BASIS } from '../lib/format'
import type { UserRecipeIngredient } from '../lib/api'

// 유저 레시피 상세(MyRecipeDetail·SharedRecipe)의 재료 최저가·영양 패널 — 만개 상세(RecipeDetail)와 동일 룩.
// 이름→item_id read-time 매칭으로 채워진 필드를 표시. 미매칭 재료는 '-'(만개 상세와 동일 처리).
// 수량이 자유텍스트('약간·1큰술')라 레시피 총합은 제공하지 않고 100g 기준만 노출(만개와 동일 각주).
const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }
const th: React.CSSProperties = { textAlign: 'left', padding: '7px 8px', borderBottom: '2px solid #E6E6E6', fontSize: 11.5, color: '#5E5E5E', fontWeight: 600 }
const td: React.CSSProperties = { padding: '10px 8px', borderBottom: '1px solid #EFEFEF' }

const g1 = (v?: number | null) => (v == null ? '-' : v.toFixed(1))
const i0 = (v?: number | null) => (v == null ? '-' : String(Math.round(v)))
// 사용량 비용 미산정 사유 → 표시 라벨 (만개 상세 usage 경로)
const COST_LABEL: Record<string, string> = { excluded_liquid: '제외', no_convert: '소량', no_price: '-' }

function priceChip(ing: UserRecipeIngredient) {
  if (ing.lowest_krw_per_100g != null) {
    const src = SRC_LABEL[ing.lowest_source ?? ''] ?? ing.lowest_source ?? '시세'
    return <span style={{ padding: '2px 7px', fontSize: 11, background: '#FCEBDD', color: '#F26419', fontWeight: 600 }}>{src}</span>
  }
  return <span style={{ padding: '2px 7px', fontSize: 11, background: '#F0F0F0', color: '#9A9A9A', fontWeight: 600 }}>미매칭</span>
}

export default function IngredientPanels({ ingredients, onAddCart }: {
  ingredients: UserRecipeIngredient[]
  onAddCart?: () => void   // 제공 시 최저가 패널 푸터에 '담기' 버튼(RecipeDetail과 동일)
}) {
  const matched = ingredients.filter((g) => g.lowest_krw_per_100g != null)
  const sum100g = matched.reduce((a, g) => a + (g.lowest_krw_per_100g ?? 0), 0)
  const nutMatched = ingredients.filter((g) => g.kcal_100g != null).length
  // 만개 상세는 사용량 기준 비용(usage_krw·cost_basis) 제공 → 사용량 표시. 유저작성 레시피는 미제공 → 100g 폴백.
  const hasUsage = ingredients.some((g) => g.cost_basis != null)
  const usageTotal = ingredients.reduce((a, g) => a + (g.usage_krw ?? 0), 0)
  const costedCount = ingredients.filter((g) => g.usage_krw != null).length

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0 }}>재료 · 실시간 최저가</h3>
          <span style={{ fontSize: 11.5, color: '#9A9A9A' }}>{PRICE_BASIS} · {hasUsage ? '레시피 사용량 기준' : '100g 환산'}</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr>
                <th style={th}>재료</th>
                <th style={th}>수량</th>
                <th style={th}>출처</th>
                <th style={{ ...th, textAlign: 'right' }}>{hasUsage ? '재료비' : '최저가(100g)'}</th>
              </tr>
            </thead>
            <tbody>
              {ingredients.map((g, i) => {
                const last = i === ingredients.length - 1
                const cell = last ? { padding: '10px 8px' } : td
                const has = g.lowest_krw_per_100g != null
                const costed = g.usage_krw != null
                const costText = hasUsage
                  ? (costed ? `${won(g.usage_krw)}원` : (COST_LABEL[g.cost_basis ?? ''] ?? '-'))
                  : (has ? `${won(g.lowest_krw_per_100g)}원` : '-')
                const strong = hasUsage ? costed : has
                return (
                  <tr key={i}>
                    <td style={cell}>{g.name}</td>
                    <td style={cell}>{g.quantity || '-'}</td>
                    <td style={cell}>{priceChip(g)}</td>
                    <td className="num" style={{ ...cell, textAlign: 'right', fontWeight: strong ? 700 : 400, color: strong ? '#17264A' : '#B5B5B5' }}>
                      {costText}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div style={{ marginTop: 14, padding: '14px 16px', background: '#FCEBDD', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontSize: 12, color: '#F26419' }}>
              {hasUsage
                ? `재료비 산정 ${costedCount}/${ingredients.length}개 · 소금·육수 등 제외 · 레시피 재료비`
                : `가격 확인된 재료 ${matched.length}/${ingredients.length}개 · 100g 최저가 합`}
            </div>
            <div className="num" style={{ fontSize: 20, fontWeight: 800, color: '#F26419' }}>{won(hasUsage ? usageTotal : sum100g)}원</div>
          </div>
          {onAddCart && (
            <button onClick={onAddCart} style={{ padding: '10px 16px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>담기</button>
          )}
        </div>
      </div>

      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0 }}>영양성분 · 재료 100g 기준</h3>
          <span style={{ fontSize: 11.5, color: '#9A9A9A' }}>식약처 식품영양DB</span>
        </div>
        {nutMatched === 0 ? (
          <div style={{ color: '#9A9A9A', fontSize: 13 }}>영양 정보가 매칭된 재료가 없어요.</div>
        ) : (
          <>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={th}>재료</th>
                    <th style={{ ...th, textAlign: 'right' }}>칼로리<span style={{ color: '#B5B5B5', fontWeight: 400 }}> ㎉</span></th>
                    <th style={{ ...th, textAlign: 'right' }}>단백<span style={{ color: '#B5B5B5', fontWeight: 400 }}> g</span></th>
                    <th style={{ ...th, textAlign: 'right' }}>탄수<span style={{ color: '#B5B5B5', fontWeight: 400 }}> g</span></th>
                    <th style={{ ...th, textAlign: 'right' }}>지방<span style={{ color: '#B5B5B5', fontWeight: 400 }}> g</span></th>
                    <th style={{ ...th, textAlign: 'right' }}>나트륨<span style={{ color: '#B5B5B5', fontWeight: 400 }}> ㎎</span></th>
                  </tr>
                </thead>
                <tbody>
                  {ingredients.map((g, i) => {
                    const last = i === ingredients.length - 1
                    const cell = last ? { padding: '10px 8px' } : td
                    const has = g.kcal_100g != null
                    const numCell: React.CSSProperties = { ...cell, textAlign: 'right', color: has ? '#17264A' : '#D0D0D0' }
                    return (
                      <tr key={i}>
                        <td style={cell}>{g.name}</td>
                        <td className="num" style={{ ...numCell, fontWeight: has ? 700 : 400 }}>{i0(g.kcal_100g)}</td>
                        <td className="num" style={numCell}>{g1(g.protein_100g)}</td>
                        <td className="num" style={numCell}>{g1(g.carb_100g)}</td>
                        <td className="num" style={numCell}>{g1(g.fat_100g)}</td>
                        <td className="num" style={numCell}>{i0(g.sodium_100g)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div style={{ marginTop: 12, fontSize: 11.5, color: '#9A9A9A', lineHeight: 1.5 }}>
              재료 {nutMatched}/{ingredients.length}개 영양 확인 · <b style={{ color: '#5E5E5E' }}>100g당</b> 값이에요.
              수량(약간·1큰술 등)이 표준화돼 있지 않아 레시피 총합은 제공하지 않아요.
            </div>
          </>
        )}
      </div>
    </div>
  )
}
