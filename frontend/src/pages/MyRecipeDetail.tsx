import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { DEFAULT_RECIPE_THUMB } from '../lib/data'
import { useDeleteMyRecipe, useMyRecipe, usePublishMyRecipe, useUnpublishMyRecipe } from '../lib/queries'
import ShareLinkModal from '../components/ShareLinkModal'

// 내가 직접 작성한 레시피 상세(#10 '보기'). 크롤링 레시피 상세(RecipeDetail)와 동일 레이아웃으로 통일(#4).
// 유저 레시피는 item_id가 없어(자유텍스트 jsonb) 최저가·영양 테이블은 제공 불가 → 재료는 이름·수량만.
const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }

export default function MyRecipeDetail() {
  const nav = useNavigate()
  const { id } = useParams()
  const rid = Number(id)
  const { data, isLoading, error } = useMyRecipe(rid)
  const del = useDeleteMyRecipe()
  const publish = usePublishMyRecipe()
  const unpublish = useUnpublishMyRecipe()
  const [share, setShare] = useState<string | null>(null)

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

  if (isLoading) return <div style={{ color: '#9A9A9A', padding: '40px 4px' }}>불러오는 중…</div>
  if (error || !data)
    return (
      <div style={{ padding: '40px 4px' }}>
        <div style={{ color: '#F04452', fontWeight: 700, marginBottom: 8 }}>레시피를 불러오지 못했어요</div>
        <div style={{ color: '#9A9A9A', fontSize: 13 }}>{error?.message ?? '데이터 없음'}</div>
        <button onClick={() => nav('/recipebook')} style={{ marginTop: 16, padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>← 내 레시피북</button>
      </div>
    )

  return (
    <div>
      <button
        onClick={() => nav(-1)}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginBottom: 10, padding: '6px 12px 6px 8px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}
      >
        ← 뒤로
      </button>
      <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 10 }}>
        <span style={{ cursor: 'pointer' }} onClick={() => nav('/recipebook')}>내 레시피북</span> / {data.title}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 10.5, fontWeight: 700, color: '#F26419', background: '#FCEBDD', padding: '3px 8px' }}>내가 만든</span>
          {data.is_public && <span style={{ fontSize: 10.5, fontWeight: 700, color: '#1B7A46', background: '#E7F5EC', padding: '3px 8px' }}>공개중</span>}
          <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>{data.title}</h1>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={onShare} disabled={publish.isPending} style={{ padding: '9px 14px', border: '1.5px solid #F26419', background: '#fff', color: '#F26419', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
            {publish.isPending ? '공개 중…' : data.is_public ? '공유 링크' : '레시피 공유'}
          </button>
          {data.is_public && (
            <button onClick={onUnpublish} disabled={unpublish.isPending} style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#9A9A9A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>공개 취소</button>
          )}
          <button onClick={onDelete} disabled={del.isPending} style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#9A9A9A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>삭제</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 16 }}>
        {/* 좌: 사진 + 조리순서 */}
        <div>
          <img src={data.image_url || DEFAULT_RECIPE_THUMB} style={{ width: '100%', aspectRatio: '16/10', objectFit: 'cover', display: 'block', background: '#F0F0F0' }} />
          <div style={{ ...card, marginTop: 16 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>조리 순서</h3>
            {data.steps.length === 0 && <div style={{ color: '#9A9A9A', fontSize: 13 }}>조리 순서 정보가 없어요.</div>}
            {data.steps.map((s, i) => (
              <div key={i} style={{ display: 'flex', gap: 12, padding: '10px 0', fontSize: 13.5, lineHeight: 1.6, borderTop: i > 0 ? '1px solid #EFEFEF' : 'none' }}>
                <span style={{ flexShrink: 0, width: 22, height: 22, borderRadius: '50%', background: '#FCEBDD', color: '#F26419', fontWeight: 700, fontSize: 12, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{i + 1}</span>
                {s}
              </div>
            ))}
          </div>
        </div>
        {/* 우: 재료(이름·수량) */}
        <div>
          <div style={card}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>재료</h3>
            {data.ingredients.length === 0 ? (
              <div style={{ color: '#9A9A9A', fontSize: 13 }}>재료 정보가 없어요.</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13.5 }}>
                <tbody>
                  {data.ingredients.map((g, i) => (
                    <tr key={i}>
                      <td style={{ padding: '10px 8px', borderBottom: i < data.ingredients.length - 1 ? '1px solid #EFEFEF' : 'none' }}>{g.name}</td>
                      <td style={{ padding: '10px 8px', borderBottom: i < data.ingredients.length - 1 ? '1px solid #EFEFEF' : 'none', textAlign: 'right', color: '#5E5E5E' }}>{g.quantity || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div style={{ marginTop: 14, fontSize: 11.5, color: '#9A9A9A', lineHeight: 1.5 }}>
              직접 작성한 레시피는 표준 품목 매칭이 없어 최저가·영양 정보는 제공하지 않아요.
            </div>
          </div>
        </div>
      </div>

      <ShareLinkModal
        open={!!share}
        onClose={() => setShare(null)}
        title="레시피 공유"
        heading={<><b style={{ color: '#17264A' }}>{data.title}</b> 을(를) 레시피 목록에 공개했어요. 이 링크로 누구나 열어볼 수 있어요.</>}
        link={share ?? ''}
      />
    </div>
  )
}
