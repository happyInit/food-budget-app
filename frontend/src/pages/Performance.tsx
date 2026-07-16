import PerformancePanel from '../components/PerformancePanel'

// 성과지표 전체 페이지 — 실데이터는 PerformancePanel(식비요약·카테고리·냉장고 통계) 단일 소스.
export default function Performance() {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>성과지표</h1>
      </div>
      <PerformancePanel />
    </div>
  )
}
