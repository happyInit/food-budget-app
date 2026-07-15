const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }

// 성과지표 콘텐츠 (시트/페이지 공용). 헤더는 감싸는 쪽에서 처리.
export default function PerformancePanel() {
  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        <span style={{ padding: '6px 12px', fontSize: 12.5, fontWeight: 700, border: '1.5px solid #F26419', background: '#FCEBDD', color: '#F26419', cursor: 'pointer' }}>이번 달</span>
        <span style={{ padding: '6px 12px', fontSize: 12.5, fontWeight: 600, border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', cursor: 'pointer' }}>지난 3개월</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 16 }}>
        {/* 도넛 */}
        <div style={{ ...card, padding: 24, textAlign: 'center' }}>
          <div style={{ width: 150, height: 150, borderRadius: '50%', background: 'conic-gradient(#1E5F96 0deg 219deg,#EFEFEF 219deg)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 14px' }}>
            <div style={{ width: 112, height: 112, borderRadius: '50%', background: '#fff', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
              <div style={{ fontSize: 28, fontWeight: 800, color: '#1E5F96' }}>61%</div>
              <div style={{ fontSize: 11, color: '#9A9A9A' }}>예산 잔여</div>
            </div>
          </div>
          <div style={{ fontSize: 14, fontWeight: 700 }}>예산 달성 순항 중</div>
          <div style={{ fontSize: 12.5, color: '#9A9A9A', marginTop: 4 }}>이 페이스면 월말 <b style={{ color: '#1E5F96' }}>+42,000원</b> 절약 예상</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={card}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 14px' }}>이번 달 성과</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {[['4종', '안 버린 재료', '#1E5F96', '#E7EFF8'], ['27,000원', '재고 활용 절약', '#F26419', '#FCEBDD'], ['18회', '집밥 요리', '#F26419', '#FCEBDD'], ['70%', '집밥 비중', '#17264A', '#F7F7F7']].map(([v, k, c, bg]) => (
                <div key={k} style={{ background: bg as string, padding: 14 }}>
                  <div className="num" style={{ fontSize: 22, fontWeight: 800, color: c as string }}>{v}</div>
                  <div style={{ fontSize: 12, color: '#5E5E5E', marginTop: 2 }}>{k}</div>
                </div>
              ))}
            </div>
          </div>
          <div style={card}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>식비 구성</h3>
            {[['집밥 (재료비)', '68,400원 · 58%'], ['외식', '35,000원 · 30%'], ['카페 / 간식', '14,200원 · 12%']].map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', fontSize: 13, borderTop: '1px solid #EFEFEF' }}>
                <span>{k}</span>
                <span className="num" style={{ fontWeight: 600 }}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
