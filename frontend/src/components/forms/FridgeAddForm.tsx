import { useState } from 'react'
import { inp, lab, primaryBtn, ghostBtn } from './formStyles'
import { useAddPantryItem } from '../../lib/queries'
import { formToRequest } from '../../lib/pantry'
import type { Storage } from '../../lib/types'

// 재료 직접 등록 (모달 콘텐츠). 저장 시 POST /api/pantry/items(#12), 성공하면 onDone.
const STORAGES: { v: Storage; label: string }[] = [
  { v: 'ROOM', label: '실온' },
  { v: 'FRIDGE', label: '냉장' },
  { v: 'FREEZER', label: '냉동' },
]

export default function FridgeAddForm({ onDone }: { onDone: () => void }) {
  const add = useAddPantryItem()
  const [name, setName] = useState('')
  const [qty, setQty] = useState('1')
  const [unit, setUnit] = useState('개')
  const [expire, setExpire] = useState('')
  const [storage, setStorage] = useState<Storage>('FRIDGE')

  const submit = () => {
    if (!name.trim()) return // A05: 서버도 min_length=1 로 막지만, UX상 미리 방지
    add.mutate(formToRequest({ name, qty, unit, expire, storage }), { onSuccess: onDone })
  }

  return (
    <div>
      <label style={lab}>재료명</label>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="예: 대파 (입력 시 표준 재료 자동완성)" style={inp} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={lab}>수량</label>
          <input value={qty} onChange={(e) => setQty(e.target.value)} style={inp} />
        </div>
        <div>
          <label style={lab}>단위</label>
          <input value={unit} onChange={(e) => setUnit(e.target.value)} style={inp} />
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={lab}>소비기한 <span style={{ color: '#9A9A9A', fontWeight: 400 }}>(비우면 추정)</span></label>
          <input type="date" value={expire} onChange={(e) => setExpire(e.target.value)} style={inp} />
        </div>
        <div>
          <label style={lab}>보관 위치</label>
          <select value={storage} onChange={(e) => setStorage(e.target.value as Storage)} style={inp}>
            {STORAGES.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
          </select>
        </div>
      </div>
      {add.error && <p style={{ color: '#F04452', fontSize: 12.5, margin: '2px 0 10px' }}>{(add.error as Error).message}</p>}
      <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
        <button onClick={onDone} style={{ ...ghostBtn, flex: 1 }}>취소</button>
        <button
          onClick={submit}
          disabled={!name.trim() || add.isPending}
          style={{ ...primaryBtn, flex: 2, opacity: !name.trim() || add.isPending ? 0.6 : 1, cursor: !name.trim() || add.isPending ? 'not-allowed' : 'pointer' }}
        >
          {add.isPending ? '저장 중…' : '저장'}
        </button>
      </div>
    </div>
  )
}
