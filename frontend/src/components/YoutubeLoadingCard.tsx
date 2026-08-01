import { useExtraction } from '../lib/extraction'

// 레시피북 그리드에 뜨는 "유튜브 추출" 카드 — 일반 레시피 카드와 동일 톤.
// 진행(analyzing) → 완료(done, '확인하고 담기') → 저장(saving) → 오류(error).
export default function YoutubeLoadingCard({ onReview }: { onReview: () => void }) {
  const ext = useExtraction()
  if (!ext || !ext.active) return null
  const { phase, result, error, dismiss } = ext
  const isErr = phase === 'error'
  const isDone = phase === 'done'

  return (
    <div style={{ background: '#fff', border: `1px solid ${isErr ? '#F3C0C0' : isDone ? '#F26419' : '#F0D6C2'}`, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div style={{ height: 108, background: isErr ? '#FDECEC' : '#FAF3EE', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {isErr ? (
          <span style={{ fontSize: 26 }}>⚠️</span>
        ) : isDone ? (
          <span style={{ width: 34, height: 34, borderRadius: '50%', background: '#F26419', color: '#fff', fontSize: 19, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>✓</span>
        ) : (
          <span style={{ width: 26, height: 26, border: '3px solid #F3DAC7', borderTopColor: '#F26419', borderRadius: '50%', animation: 'fbspin 0.8s linear infinite' }} />
        )}
      </div>
      <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
        <span style={{ fontSize: 10.5, fontWeight: 700, color: '#F26419', background: '#FCEBDD', padding: '2px 6px', alignSelf: 'flex-start' }}>YouTube</span>
        <div style={{ fontSize: 13.5, fontWeight: 700, lineHeight: 1.35, color: isErr ? '#E34948' : '#0B0B0B', overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
          {isErr ? '분석 실패' : isDone ? (result?.title ?? '분석 완료') : phase === 'saving' ? '레시피 저장 중…' : '영상 분석 중…'}
        </div>
        <div style={{ fontSize: 11.5, color: isDone ? '#1BAF7A' : '#9A9A9A', fontWeight: isDone ? 700 : 400, lineHeight: 1.45 }}>
          {isErr ? (error ?? '다시 시도해 주세요') : isDone ? '✓ 분석 완료 · 확인이 필요해요' : phase === 'saving' ? '레시피북에 담는 중…' : '재료·조리 순서를 정리하고 있어요'}
        </div>
        {isDone && (
          <button onClick={onReview} style={{ marginTop: 'auto', padding: '8px 0', border: 'none', background: '#F26419', color: '#fff', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>확인하고 담기</button>
        )}
        {isErr && (
          <button onClick={dismiss} style={{ marginTop: 'auto', padding: '7px 0', border: '1.5px solid #E6E6E6', background: '#fff', color: '#9A9A9A', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>닫기</button>
        )}
      </div>
    </div>
  )
}
