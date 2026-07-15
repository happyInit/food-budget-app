import { useState } from 'react'
import { inp, lab, primaryBtn, ghostBtn } from './formStyles'

const cats = ['장보기', '외식', '배달', '기타']

// 지출 직접 기록 (모달 콘텐츠).
export default function ExpenseAddForm({ onDone }: { onDone: () => void }) {
  const [cat, setCat] = useState('외식')
  return (
    <div>
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
        <button onClick={onDone} style={{ ...ghostBtn, flex: 1 }}>취소</button>
        <button onClick={onDone} style={{ ...primaryBtn, flex: 2 }}>저장</button>
      </div>
    </div>
  )
}
