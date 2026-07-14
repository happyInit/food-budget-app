import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

const inp: React.CSSProperties = { width: '100%', margin: '6px 0 16px', padding: '11px 13px', border: '1.5px solid #E6E6E6', fontSize: 14, outline: 'none', boxSizing: 'border-box' }
const lab: React.CSSProperties = { fontSize: 12.5, fontWeight: 600, color: '#5E5E5E' }
const cats = ['장보기', '외식', '배달', '기타']

export default function ExpenseAdd() {
  const nav = useNavigate()
  const [cat, setCat] = useState('외식')
  return (
    <div>
      <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 10 }}>
        <span style={{ cursor: 'pointer' }} onClick={() => nav('/expense')}>식비 캘린더</span> / 지출 추가
      </div>
      <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: '0 0 20px' }}>지출 직접 기록</h1>
      <div style={{ maxWidth: 520, background: '#fff', border: '1px solid #E6E6E6', padding: 24 }}>
        <label style={lab}>날짜</label>
        <input defaultValue="2026-07-13" style={inp} />
        <label style={lab}>분류</label>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '8px 0 16px' }}>
          {cats.map((c) => {
            const on = c === cat
            return (
              <span key={c} onClick={() => setCat(c)} style={{ padding: '8px 13px', fontSize: 13, fontWeight: on ? 700 : 600, border: on ? '1.5px solid #F26419' : '1.5px solid #E6E6E6', background: on ? '#FCEBDD' : '#fff', color: on ? '#F26419' : '#5E5E5E', cursor: 'pointer' }}>{c}</span>
            )
          })}
        </div>
        <label style={lab}>내용</label>
        <input placeholder="예: 김밥천국 점심" style={inp} />
        <label style={lab}>금액</label>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, margin: '6px 0 20px', border: '1.5px solid #E6E6E6', padding: '11px 13px' }}>
          <input defaultValue="7,000" className="num" style={{ flex: 1, border: 'none', outline: 'none', fontSize: 16, fontWeight: 700, textAlign: 'right', minWidth: 0 }} />
          <span style={{ fontSize: 14, color: '#5E5E5E' }}>원</span>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={() => nav('/expense')} style={{ flex: 1, padding: 12, border: '1.5px solid #E6E6E6', background: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>취소</button>
          <button onClick={() => nav('/expense')} style={{ flex: 2, padding: 12, border: 'none', background: '#F26419', color: '#fff', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>저장</button>
        </div>
      </div>
    </div>
  )
}
