import { useState } from 'react'
import { useItemSearch, useWatchList, useAddWatch, useRemoveWatch } from '../lib/queries'

/**
 * 최저가 관심품목 관리 (api-spec #29·#30).
 *
 * **왜 필요한가.** 가격 이상탐지 → Kafka → fan-out 컨슈머까지 전부 구현돼 있지만,
 * 알림은 **관심 등록한 유저에게만** 나간다. 등록이 0건이면 파이프라인 전체가 비어 있는 것과 같다
 * (실측 2026-07-29: `price.price_watch` 0행 — 등록 UI 가 없어서였다).
 *
 * 독립 관심사라 페이지에 붙박지 않고 컴포넌트로 뺀다 — 핫딜·품목상세 어디에도 얹을 수 있다.
 */
const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }

export default function PriceWatchPanel() {
  const [q, setQ] = useState('')
  const search = useItemSearch(q)
  const list = useWatchList()
  const add = useAddWatch()
  const remove = useRemoveWatch()

  const watched = list.data?.items ?? []
  const watchedIds = new Set(watched.map((w) => w.item_id))
  const hits = (search.data?.items ?? []).filter((i) => !watchedIds.has(i.item_id)).slice(0, 6)

  return (
    <div style={card}>
      <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 4px' }}>관심 품목 최저가 알림</h3>
      <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 12 }}>
        등록해 두면 가격이 크게 떨어졌을 때 알림을 보내드려요. 같은 품목은 7일에 한 번만 알려요.
      </div>

      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="품목 검색 (예: 삼겹살)"
        style={{ width: '100%', padding: '10px 12px', border: '1.5px solid #E6E6E6', fontSize: 13.5, outline: 'none', boxSizing: 'border-box' }}
      />

      {q.trim().length > 0 && hits.length > 0 && (
        <div style={{ marginTop: 8 }}>
          {hits.map((i) => (
            <div key={i.item_id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '7px 0', borderTop: '1px solid #EFEFEF' }}>
              <span style={{ fontSize: 13 }}>{i.canonical_name}</span>
              <button
                onClick={() => add.mutate(i.item_id, { onSuccess: () => setQ('') })}
                disabled={add.isPending}
                style={{ padding: '4px 11px', border: 'none', background: '#F26419', color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}
              >담기</button>
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 14 }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: '#5E5E5E', marginBottom: 6 }}>
          등록한 품목 {watched.length}개
        </div>
        {watched.length === 0 ? (
          <div style={{ fontSize: 12.5, color: '#9A9A9A' }}>아직 등록한 품목이 없어요.</div>
        ) : (
          watched.map((w) => (
            <div key={w.item_id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '7px 0', borderTop: '1px solid #EFEFEF' }}>
              <span style={{ fontSize: 13 }}>{w.canonical_name ?? `품목 ${w.item_id}`}</span>
              <button
                onClick={() => remove.mutate(w.item_id)}
                disabled={remove.isPending}
                style={{ padding: '4px 11px', border: '1px solid #E6E6E6', background: '#fff', color: '#9A9A9A', fontSize: 12, cursor: 'pointer' }}
              >해제</button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
