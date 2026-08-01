import { type CSSProperties } from 'react'
import { useExtraction } from '../../lib/extraction'
import { won } from '../../lib/api'

const chip: CSSProperties = { padding: '4px 10px', fontSize: 11.5, fontWeight: 700, background: '#F0F0F0', color: '#5E5E5E' }

// 추출 완료 결과 확인 → '레시피북에 담기'(확정). Modal 콘텐츠.
export default function YoutubeConfirmForm() {
  const ext = useExtraction()
  const r = ext?.result
  if (!r || r.status !== 'DONE') return null
  const saving = ext?.phase === 'saving'

  return (
    <div>
      <h3 style={{ fontSize: 17, fontWeight: 800, letterSpacing: '-.3px', margin: '0 0 10px' }}>{r.title ?? '제목 없음'}</h3>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
        <span style={chip}>재료 {r.ingredients.length}개</span>
        <span style={chip}>조리 {r.steps.length}단계</span>
        {r.cost?.total_krw != null && <span style={{ ...chip, background: '#FCEBDD', color: '#F26419' }}>재료비 {won(r.cost.total_krw)}원~</span>}
      </div>

      <div style={{ fontSize: 12.5, fontWeight: 700, color: '#5E5E5E', margin: '0 0 6px' }}>재료</div>
      <div style={{ background: '#FAF8F5', border: '1px solid #E6E6E6', padding: '4px 14px', maxHeight: 170, overflowY: 'auto', marginBottom: 14 }}>
        {r.ingredients.map((g, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13, padding: '7px 0', borderTop: i ? '1px solid #EFEFEF' : 'none' }}>
            <span>{g.name}</span>
            <span style={{ color: '#9A9A9A', flexShrink: 0 }}>{g.quantity ?? '-'}</span>
          </div>
        ))}
      </div>

      {ext?.error && (
        <div style={{ background: '#FDECEC', color: '#E34948', fontSize: 12.5, padding: '10px 12px', marginBottom: 10 }}>{ext.error}</div>
      )}

      <button
        onClick={() => ext?.confirm()}
        disabled={saving}
        style={{ width: '100%', padding: '13px 16px', border: 'none', background: saving ? '#C9C9C9' : '#F26419', color: '#fff', fontSize: 14, fontWeight: 700, cursor: saving ? 'default' : 'pointer' }}
      >
        {saving ? '담는 중…' : '레시피북에 담기'}
      </button>
      <div style={{ fontSize: 11.5, color: '#B0B0B0', marginTop: 10, textAlign: 'center' }}>담은 뒤 레시피 상세에서 재료·순서를 수정할 수 있어요.</div>
    </div>
  )
}
