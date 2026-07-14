import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AuthWrap, { authCard, primaryBtn } from './AuthWrap'

const presets = ['20만', '30만', '40만', '50만']

export default function BudgetSetup() {
  const nav = useNavigate()
  const [sel, setSel] = useState('30만')
  return (
    <AuthWrap>
      <div style={{ textAlign: 'center', marginBottom: 24 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#F26419', letterSpacing: '1px' }}>STEP 1 / 1</div>
        <div style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', marginTop: 8 }}>한 달 식비 예산을<br />정해주세요</div>
        <div style={{ fontSize: 13, color: '#5E5E5E', marginTop: 10 }}>추천·장바구니 계산의 기준이 됩니다. 나중에 언제든 바꿀 수 있어요.</div>
      </div>
      <div style={authCard}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, border: '1.5px solid #F26419', padding: '14px 16px', background: '#FCEBDD' }}>
          <span style={{ fontSize: 22, fontWeight: 800, color: '#F26419' }}>₩</span>
          <input defaultValue="300,000" className="num" style={{ flex: 1, border: 'none', background: 'none', fontSize: 28, fontWeight: 800, color: '#17264A', outline: 'none', textAlign: 'right', minWidth: 0 }} />
          <span style={{ fontSize: 15, color: '#5E5E5E', fontWeight: 600 }}>원</span>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          {presets.map((p) => {
            const on = p === sel
            return (
              <button key={p} onClick={() => setSel(p)} style={{ flex: 1, padding: 9, border: on ? '1.5px solid #F26419' : '1px solid #E6E6E6', background: on ? '#FCEBDD' : '#fff', fontSize: 13, fontWeight: on ? 700 : 600, color: on ? '#F26419' : '#5E5E5E', cursor: 'pointer' }}>{p}</button>
            )
          })}
        </div>
        <div style={{ marginTop: 16, padding: '12px 14px', background: '#E7EFF8', fontSize: 12.5, color: '#1E5F96', display: 'flex', alignItems: 'center', gap: 8 }}>
          가입 축하 <b>1,000P</b> 지급! 레시피 등록 시마다 추가 적립
        </div>
        <button onClick={() => nav('/home')} style={{ ...primaryBtn, padding: 14, marginTop: 16 }}>시작하기</button>
      </div>
    </AuthWrap>
  )
}
