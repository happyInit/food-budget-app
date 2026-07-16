import { useMemo, useState } from 'react'
import { usePantryItems, usePatchPantryItem, useDeletePantryItem } from '../lib/queries'
import { storageToZone, toDisplay, type PantryVM, type ZoneKey } from '../lib/pantry'
import Modal from '../components/Modal'
import OcrFlow from '../components/forms/OcrFlow'
import FridgeAddForm from '../components/forms/FridgeAddForm'
import FridgeCard from '../components/FridgeCard'

// 내 냉장고 — Home과 동일한 FridgeCard 디자인. 재료 ⋯ 로 먹음/버림(성과 반영)·오입력 삭제.
export default function Fridge() {
  const { data: rows = [], isLoading, error } = usePantryItems()
  const patch = usePatchPantryItem()
  const del = useDeletePantryItem()
  const [action, setAction] = useState<PantryVM | null>(null)   // 정리 모달 대상 재료
  const [modal, setModal] = useState<null | 'ocr' | 'add'>(null)

  // 서버 행 → zone별 표시 VM (Home과 동일 로직·컴포넌트).
  const zones = useMemo(() => {
    const today = new Date()
    const z: Record<ZoneKey, PantryVM[]> = { room: [], fridge: [], freezer: [] }
    for (const r of rows) z[storageToZone(r.storage)].push(toDisplay(r, today))
    return z
  }, [rows])

  // 정리: 먹음/버림 = status 전이(#13, 소비 실천율 반영) · 삭제 = 하드삭제(#14, 오입력 정정).
  const consume = () => { if (action) patch.mutate({ id: action.id, patch: { status: 'CONSUMED' } }); setAction(null) }
  const discard = () => { if (action) patch.mutate({ id: action.id, patch: { status: 'DISCARDED' } }); setAction(null) }
  const hardDelete = () => { if (action) del.mutate(action.id); setAction(null) }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 6 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>내 냉장고</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setModal('ocr')} style={{ padding: '10px 15px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>영수증 스캔</button>
          <button onClick={() => setModal('add')} style={{ padding: '10px 15px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>재료 추가</button>
        </div>
      </div>
      <p style={{ fontSize: 13.5, color: '#5E5E5E', margin: '0 0 18px' }}>냉장고 문을 열고 재료 옆 <b>⋯</b>로 먹음·버림을 정리하면 <b style={{ color: '#F26419' }}>소비 실천율</b>에 반영돼요. 소비기한 임박은 빨갛게 표시돼요.</p>

      {isLoading && <p style={{ fontSize: 13, color: '#9A9A9A', margin: '0 0 12px' }}>재고를 불러오는 중…</p>}
      {error && <p style={{ fontSize: 13, color: '#F04452', margin: '0 0 12px' }}>재고를 불러오지 못했어요: {(error as Error).message}</p>}
      {!isLoading && !error && rows.length === 0 && (
        <p style={{ fontSize: 13, color: '#9A9A9A', margin: '0 0 12px' }}>아직 등록한 재료가 없어요. <b>재료 추가</b>로 시작해요.</p>
      )}

      <div style={{ maxWidth: 560, margin: '0 auto', height: 'calc(100vh - 210px)', minHeight: 480 }}>
        <FridgeCard zones={zones} total={rows.length} mode="manage" onItemAction={(it) => setAction(it)} />
      </div>

      {/* 재료 정리 모달 — 먹음/버림(성과 반영) vs 오입력 삭제 */}
      <Modal open={!!action} onClose={() => setAction(null)} title={action ? `${action.name} 정리` : ''}>
        {action && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <p style={{ fontSize: 13, color: '#5E5E5E', margin: '0 0 4px' }}>
              이 재료를 어떻게 정리할까요? <b style={{ color: '#17264A' }}>먹음·버림</b>은 <b style={{ color: '#F26419' }}>소비 실천율</b> 통계에 반영돼요.
            </p>
            <button onClick={consume} disabled={patch.isPending}
              style={{ padding: '12px 14px', border: '1.5px solid #1E5F96', background: '#E7EFF8', color: '#1E5F96', fontSize: 14, fontWeight: 700, cursor: 'pointer', textAlign: 'left' }}>
              🍽 다 먹었어요 <span style={{ fontWeight: 400, color: '#5E7A96' }}>· 안 버린 재료로 집계</span>
            </button>
            <button onClick={discard} disabled={patch.isPending}
              style={{ padding: '12px 14px', border: '1.5px solid #F04452', background: '#FDECEC', color: '#F04452', fontSize: 14, fontWeight: 700, cursor: 'pointer', textAlign: 'left' }}>
              🗑 버렸어요 <span style={{ fontWeight: 400, color: '#B5666B' }}>· 버린 재료로 집계</span>
            </button>
            <button onClick={hardDelete} disabled={del.isPending}
              style={{ padding: '10px 14px', border: '1px solid #E6E6E6', background: '#fff', color: '#9A9A9A', fontSize: 13, fontWeight: 700, cursor: 'pointer', textAlign: 'left' }}>
              ✎ 잘못 입력이라 그냥 삭제 <span style={{ fontWeight: 400 }}>· 통계 미반영</span>
            </button>
          </div>
        )}
      </Modal>

      <Modal open={modal === 'ocr'} onClose={() => setModal(null)} title="영수증으로 재고 등록">
        <OcrFlow onDone={() => setModal(null)} />
      </Modal>
      <Modal open={modal === 'add'} onClose={() => setModal(null)} title="재료 직접 등록">
        <FridgeAddForm onDone={() => setModal(null)} />
      </Modal>
    </div>
  )
}
