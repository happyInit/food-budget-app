import { primaryBtn } from './formStyles'

const card: React.CSSProperties = { background: '#FAF8F5', border: '1px solid #E6E6E6', padding: 16 }

// YouTube URL 추출 (모달 콘텐츠) → 내 레시피북에 저장.
export default function YoutubeExtractForm({ onDone }: { onDone: () => void }) {
  return (
    <div>
      <div style={{ border: '2px dashed #E6E6E6', padding: '30px 24px', textAlign: 'center', marginBottom: 14 }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>YouTube URL을 붙여넣으세요</div>
        <div style={{ fontSize: 12.5, color: '#9A9A9A', marginTop: 6 }}>영상 멀티모달 분석 → 재료·조리단계를 추출해 레시피북에 담아요</div>
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input placeholder="https://youtube.com/watch?v=…" style={{ flex: 1, padding: '11px 14px', border: '1.5px solid #E6E6E6', fontSize: 14, outline: 'none', minWidth: 0 }} />
        <button onClick={onDone} style={{ ...primaryBtn, padding: '0 18px', whiteSpace: 'nowrap' }}>추출</button>
      </div>
      <div style={card}>
        <div style={{ fontSize: 12.5, fontWeight: 700, marginBottom: 8 }}>추출 파이프라인</div>
        <div style={{ fontSize: 12.5, color: '#5E5E5E', lineHeight: 2 }}>
          1. 영상 사전필터 · 캐시 확인<br />
          2. Gemini 멀티모달 → 재료·단계 추출<br />
          3. CRF NER → 재료 정규화<br />
          4. 마켓컬리 상품 매핑 · 가격 산출<br />
          5. 결과 확인·수정 → 레시피북 저장
        </div>
      </div>
      <div style={{ background: '#FCEBDD', color: '#F26419', fontSize: 12, padding: '11px 14px', marginTop: 12 }}>요리 영상이 아니거나 추출 실패 시 안내됩니다. (비용 상한 관리)</div>
    </div>
  )
}
