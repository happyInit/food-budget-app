import type { CSSProperties } from 'react'
import type { RecipeReviews } from '../lib/api'

// #10 요리후기 감정·요약 카드 — 조리순서 카드와 동일 톤(흰 배경·회색 보더·오렌지 액센트).
// 감정=nova-micro, 요약=claude-3.5-sonnet 결과를 유저가 "이 레시피 후기 어때?" 한눈에.
const card: CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }

export default function ReviewSummaryCard({ data }: { data: RecipeReviews }) {
  const rate = data.positive_rate
  return (
    <div style={{ ...card, marginTop: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, margin: 0 }}>후기 요약</h3>
        {/* AI 생성물 투명성 배지 */}
        <span style={{ padding: '3px 8px', fontSize: 10.5, fontWeight: 700, background: '#E7EFF8', color: '#1E5F96' }}>AI 분석</span>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: '#9A9A9A' }}>
          {data.review_count.toLocaleString()}개 후기 기반
        </span>
      </div>

      {rate != null && (
        <div style={{ marginBottom: data.summary ? 16 : 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, marginBottom: 7 }}>
            <span style={{ fontSize: 28, fontWeight: 800, color: '#F26419', letterSpacing: '-1px' }}>
              {Math.round(rate)}%
            </span>
            <span style={{ fontSize: 13, fontWeight: 700, color: '#5E5E5E' }}>가 긍정적이에요</span>
          </div>
          <div style={{ height: 8, background: '#F0F0F0', overflow: 'hidden' }}>
            <div style={{ width: `${Math.max(0, Math.min(100, rate))}%`, height: '100%', background: '#F26419' }} />
          </div>
        </div>
      )}

      {data.summary && (
        <p style={{ fontSize: 13.5, lineHeight: 1.75, color: '#3A3A3A', margin: 0 }}>{data.summary}</p>
      )}

      {data.caution && (
        <div style={{ marginTop: 12, padding: '10px 12px', background: '#FEF6ED', border: '1px solid #F6D9BE', fontSize: 12.5, lineHeight: 1.6, color: '#B45309', display: 'flex', gap: 8 }}>
          <span style={{ flexShrink: 0 }}>⚠️</span>
          <span>{data.caution}</span>
        </div>
      )}
    </div>
  )
}
