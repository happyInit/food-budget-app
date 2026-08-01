import { useState } from 'react'
import { useExtraction } from '../../lib/extraction'

// YouTube 요리 영상 링크 입력 → 백그라운드 추출 시작 → 즉시 닫힘.
// 진행 상황·결과는 레시피북의 로딩 카드로 노출된다(모달이 붙잡지 않는다).
export default function YoutubeExtractForm({ onDone }: { onDone: () => void }) {
  const [url, setUrl] = useState('')
  const ext = useExtraction()

  const go = () => {
    const v = url.trim()
    if (!v || !ext) return
    ext.start(v)
    onDone() // 즉시 닫힘 — 분석은 레시피북 로딩 카드로 이어짐
  }

  return (
    <div>
      <p style={{ fontSize: 13, color: '#5E5E5E', lineHeight: 1.65, margin: '0 0 14px' }}>
        요리 영상 링크를 붙여넣으면 <b style={{ color: '#F26419' }}>재료와 조리 순서를 자동으로</b> 정리해 레시피북에 담아드려요.
      </p>
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') go() }}
          placeholder="https://youtube.com/watch?v=…"
          autoFocus
          style={{ flex: 1, padding: '11px 14px', border: '1.5px solid #E6E6E6', fontSize: 14, outline: 'none', minWidth: 0 }}
        />
        <button
          onClick={go}
          disabled={!url.trim()}
          style={{ padding: '0 20px', border: 'none', background: url.trim() ? '#F26419' : '#C9C9C9', color: '#fff', fontSize: 14, fontWeight: 700, cursor: url.trim() ? 'pointer' : 'default', whiteSpace: 'nowrap' }}
        >
          추출
        </button>
      </div>
      <div style={{ fontSize: 12, color: '#9A9A9A', marginTop: 12, lineHeight: 1.6 }}>
        추출을 누르면 창이 닫히고, <b>레시피북에서 분석 진행 상황</b>을 보여드려요. 완료되면 자동으로 담깁니다.<br />
        <span style={{ color: '#B0B0B0' }}>요리 영상만 분석돼요 · 광고·브이로그 등은 자동으로 걸러집니다.</span>
      </div>
    </div>
  )
}
