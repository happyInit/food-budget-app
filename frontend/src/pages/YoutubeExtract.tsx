const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }

export default function YoutubeExtract() {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>YouTube 레시피 추출</h1>
        <span style={{ padding: '3px 9px', fontSize: 11, fontWeight: 700, background: '#E6F6EC', color: '#1FA463' }}>P1</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 16 }}>
        <div>
          <div style={{ border: '2px dashed #E6E6E6', padding: '44px 24px', textAlign: 'center', marginBottom: 14 }}>
            <div style={{ fontSize: 15, fontWeight: 700 }}>YouTube URL을 붙여넣으세요</div>
            <div style={{ fontSize: 12.5, color: '#9A9A9A', marginTop: 6 }}>영상 멀티모달 분석 → AI가 재료·조리단계를 추출합니다</div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input placeholder="https://youtube.com/watch?v=…" style={{ flex: 1, padding: '11px 14px', border: '1.5px solid #E6E6E6', fontSize: 14, outline: 'none', minWidth: 0 }} />
            <button style={{ padding: '0 18px', border: 'none', background: '#1FA463', color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' }}>추출</button>
          </div>
          <div style={{ background: '#E6F6EC', color: '#1FA463', fontSize: 12, padding: '11px 14px', marginTop: 12 }}>영상 검사 후 요리 영상이 아니거나 추출 실패 시 안내됩니다. (비용 상한 관리)</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={card}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 10px' }}>추출 파이프라인</h3>
            <div style={{ fontSize: 13, color: '#5E5E5E', lineHeight: 2.1 }}>
              1. 영상 사전필터 · 캐시 확인<br />
              2. Gemini 멀티모달 → 재료·단계 추출<br />
              3. CRF NER → 재료 정규화<br />
              4. 마켓컬리 상품 매핑 · 가격 산출<br />
              5. 결과 확인·수정 → 레시피북 저장
            </div>
          </div>
          <div style={card}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 8px' }}>최근 추출</h3>
            {[['백종원의 간장계란밥', '7/11 추출 · 재료 5개 · 1,200원'], ['자취생 10분 파스타', '7/9 추출 · 재료 7개 · 3,800원']].map(([t, s]) => (
              <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 13, padding: '11px 0', borderTop: '1px solid #EFEFEF' }}>
                <div style={{ width: 40, height: 40, background: '#FDECEC', flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600 }}>{t}</div>
                  <div style={{ fontSize: 11.5, color: '#9A9A9A' }}>{s}</div>
                </div>
                <span style={{ padding: '3px 8px', fontSize: 11, fontWeight: 700, background: '#E6F6EC', color: '#1FA463' }}>저장됨</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
