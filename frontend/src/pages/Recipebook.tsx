import { useNavigate } from 'react-router-dom'
import { img } from '../lib/data'

const filters = ['전체 23', '한식 14', '간편식 6', 'YouTube 3']

export default function Recipebook() {
  const nav = useNavigate()
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 16 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>내 레시피북</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#1A1A1A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>직접 작성</button>
          <button onClick={() => nav('/youtube')} style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>YouTube 추가</button>
          <button style={{ padding: '9px 14px', border: 'none', background: '#1FA463', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>공유</button>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 18 }}>
        {filters.map((f, i) => (
          <span key={f} style={{ padding: '7px 14px', fontSize: 13, fontWeight: i === 0 ? 700 : 600, border: i === 0 ? '1.5px solid #1FA463' : '1.5px solid #E6E6E6', background: i === 0 ? '#1FA463' : '#fff', color: i === 0 ? '#fff' : '#5E5E5E', cursor: 'pointer' }}>{f}</span>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(130px,1fr))', gap: 10 }}>
        {Array.from({ length: 12 }, (_, i) => (
          <div key={i} onClick={() => nav('/recipes/' + (i + 1))} style={{ aspectRatio: '1', cursor: 'pointer', background: `#F0F0F0 center/cover no-repeat url("${img(i, 300)}")` }} />
        ))}
      </div>
    </div>
  )
}
