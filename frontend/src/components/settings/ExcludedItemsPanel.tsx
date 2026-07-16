import { useState } from 'react'
import { useAddExcludedItem, useExcludedItems, useItemSearch, useRemoveExcludedItem } from '../../lib/queries'

// 제외(회피) 재료 설정 — 이 재료가 든 레시피를 '뭐 해먹지'/추천에서 걸러낸다(추천 반영).
export default function ExcludedItemsPanel() {
  const [q, setQ] = useState('')
  const { data: excluded = [] } = useExcludedItems()
  const { data: search, isLoading } = useItemSearch(q)
  const add = useAddExcludedItem()
  const remove = useRemoveExcludedItem()

  const excludedIds = new Set(excluded.map((e) => e.item_id))
  const results = (search?.items ?? []).filter((it) => !excludedIds.has(it.item_id)).slice(0, 8)

  return (
    <div>
      <p style={{ fontSize: 13, color: '#5E5E5E', margin: '0 0 14px', lineHeight: 1.6 }}>
        싫어하거나 못 먹는 재료를 등록하면, <b style={{ color: '#17264A' }}>이 재료가 든 레시피를 추천에서 빼드려요.</b>
      </p>

      {/* 현재 제외 목록 */}
      <div style={{ fontSize: 12, fontWeight: 700, color: '#9A9A9A', marginBottom: 8 }}>제외 중인 재료 {excluded.length}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 18, minHeight: 34 }}>
        {excluded.length === 0 ? (
          <span style={{ fontSize: 13, color: '#B5B5B5' }}>아직 제외한 재료가 없어요.</span>
        ) : (
          excluded.map((e) => (
            <span key={e.item_id} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, padding: '6px 8px 6px 12px', background: '#FDECEC', color: '#F04452', fontSize: 13, fontWeight: 700 }}>
              {e.name}
              <button onClick={() => remove.mutate(e.item_id)} disabled={remove.isPending} aria-label={`${e.name} 제외 해제`}
                style={{ width: 18, height: 18, border: 'none', background: 'rgba(240,68,82,.15)', color: '#F04452', fontSize: 11, cursor: 'pointer', lineHeight: 1 }}>✕</button>
            </span>
          ))
        )}
      </div>

      {/* 검색 추가 */}
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="재료 이름 검색 (예: 오이, 고수, 가지)"
        style={{ width: '100%', padding: '11px 13px', border: '1.5px solid #E6E6E6', fontSize: 14, outline: 'none', boxSizing: 'border-box' }}
      />
      {q.trim().length >= 1 && (
        <div style={{ marginTop: 8, border: '1px solid #EFEFEF' }}>
          {isLoading && <div style={{ padding: '12px 14px', fontSize: 13, color: '#9A9A9A' }}>검색 중…</div>}
          {!isLoading && results.length === 0 && <div style={{ padding: '12px 14px', fontSize: 13, color: '#9A9A9A' }}>결과가 없어요.</div>}
          {results.map((it) => (
            <button
              key={it.item_id}
              onClick={() => { add.mutate({ item_id: it.item_id, name: it.canonical_name }); setQ('') }}
              disabled={add.isPending}
              style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '11px 14px', border: 'none', borderTop: '1px solid #EFEFEF', background: '#fff', fontSize: 13.5, color: '#17264A', cursor: 'pointer', textAlign: 'left' }}
            >
              <span style={{ color: '#F26419', fontWeight: 800 }}>＋</span>
              <b style={{ fontWeight: 700 }}>{it.canonical_name}</b>
              {it.category && <span style={{ marginLeft: 'auto', fontSize: 11, color: '#9A9A9A' }}>{it.category}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
