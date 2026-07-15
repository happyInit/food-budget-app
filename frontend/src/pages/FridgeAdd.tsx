import { useNavigate } from 'react-router-dom'
import FridgeAddForm from '../components/forms/FridgeAddForm'

// /pantry/add 단독 페이지 — 모달과 동일 폼(FridgeAddForm)을 재사용. 저장/취소 시 냉장고로 복귀.
export default function FridgeAdd() {
  const nav = useNavigate()
  return (
    <div>
      <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 10 }}>
        <span style={{ cursor: 'pointer' }} onClick={() => nav('/pantry')}>내 냉장고</span> / 직접 추가
      </div>
      <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: '0 0 20px' }}>재료 직접 등록</h1>
      <div style={{ maxWidth: 520, background: '#fff', border: '1px solid #E6E6E6', padding: 24 }}>
        <FridgeAddForm onDone={() => nav('/pantry')} />
      </div>
    </div>
  )
}
