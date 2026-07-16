import { useState } from 'react'
import { inp, lab, primaryBtn, ghostBtn } from './formStyles'
import { useAddPantryItem, useItemSearch } from '../../lib/queries'
import { formToRequest } from '../../lib/pantry'
import type { ItemSearchItem } from '../../lib/api'
import type { Storage } from '../../lib/types'

// 재료 직접 등록 (모달 콘텐츠). 저장 시 POST /api/pantry/items(#12), 성공하면 onDone.
// 이름 입력 → 표준품목(item_master) 검색 → 선택 시 item_id 첨부 → '뭐 해먹지' 추천에 반영.
const STORAGES: { v: Storage; label: string }[] = [
  { v: 'ROOM', label: '실온' },
  { v: 'FRIDGE', label: '냉장' },
  { v: 'FREEZER', label: '냉동' },
]

export default function FridgeAddForm({ onDone }: { onDone: () => void }) {
  const add = useAddPantryItem()
  const [name, setName] = useState('')
  const [itemId, setItemId] = useState<number | null>(null) // 표준품목 매칭 시 첨부
  const [qty, setQty] = useState('1')
  const [unit, setUnit] = useState('개')
  const [expire, setExpire] = useState('')
  const [storage, setStorage] = useState<Storage>('FRIDGE')
  const [focused, setFocused] = useState(false)

  // 표준품목 검색 — 이름 입력 중(아직 미선택)일 때만.
  const { data: search, isFetching } = useItemSearch(itemId == null ? name : '')
  const results = (search?.items ?? []).slice(0, 6)
  const showDropdown = focused && itemId == null && name.trim().length >= 1 && results.length > 0

  const onNameChange = (v: string) => { setName(v); setItemId(null) } // 재입력하면 매칭 해제
  const pick = (it: ItemSearchItem) => { setName(it.canonical_name); setItemId(it.item_id); setFocused(false) }

  const submit = () => {
    if (!name.trim()) return // A05: 서버도 min_length=1 로 막지만, UX상 미리 방지
    add.mutate(formToRequest({ name, qty, unit, expire, storage, itemId }), { onSuccess: onDone })
  }

  return (
    <div>
      <label style={lab}>재료명</label>
      <div style={{ position: 'relative' }}>
        <input
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => window.setTimeout(() => setFocused(false), 150)} // 후보 클릭 여유
          placeholder="예: 대파 — 검색해서 표준 재료를 고르면 추천에 반영돼요"
          style={inp}
        />
        {showDropdown && (
          <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 5, background: '#fff', border: '1px solid #E6E6E6', boxShadow: '0 8px 20px rgba(0,0,0,.14)', maxHeight: 210, overflowY: 'auto' }}>
            {results.map((it) => (
              <button
                key={it.item_id}
                type="button"
                onMouseDown={() => pick(it)} // onBlur보다 먼저 실행되도록 mousedown
                style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '10px 12px', border: 'none', borderTop: '1px solid #F0F0F0', background: '#fff', cursor: 'pointer', textAlign: 'left', fontSize: 13.5 }}
              >
                <span style={{ color: '#F26419', fontWeight: 800 }}>＋</span>
                <b style={{ color: '#17264A', fontWeight: 700 }}>{it.canonical_name}</b>
                {it.category && <span style={{ marginLeft: 'auto', fontSize: 11, color: '#9A9A9A' }}>{it.category}</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 매칭 상태 안내 */}
      {itemId != null ? (
        <div style={{ fontSize: 11.5, color: '#1B7A46', margin: '6px 0 2px', fontWeight: 600 }}>✓ 표준 재료로 매칭됨 — 이 재료로 만들 수 있는 추천이 떠요</div>
      ) : name.trim().length >= 1 ? (
        <div style={{ fontSize: 11.5, color: '#9A9A9A', margin: '6px 0 2px' }}>
          {isFetching ? '표준 재료 검색 중…' : '표준 재료를 선택하면 추천에 반영돼요 (그냥 저장도 가능)'}
        </div>
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 8 }}>
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
