import { useMemo, useRef, useState } from 'react'
import { img } from '../lib/data'
import { usePantryItems, usePatchPantryItem } from '../lib/queries'
import { storageToZone, toDisplay, zoneToStorage, type PantryVM, type ZoneKey } from '../lib/pantry'
import Modal from '../components/Modal'
import OcrFlow from '../components/forms/OcrFlow'
import FridgeAddForm from '../components/forms/FridgeAddForm'

const URG = {
  danger: { c: '#F04452', bg: '#FDECEC' },
  warn: { c: '#F26419', bg: '#FCEBDD' },
  ok: { c: '#1E5F96', bg: '#E7EFF8' },
}

type Zones = Record<ZoneKey, PantryVM[]>

function ItemCard({ it, zone, onDragStart, onDragEnd, dragging }: {
  it: PantryVM; zone: ZoneKey; dragging: boolean
  onDragStart: (zone: ZoneKey, id: number) => void; onDragEnd: () => void
}) {
  const u = URG[it.urg]
  return (
    <div
      draggable
      onDragStart={(e) => { e.dataTransfer.effectAllowed = 'move'; onDragStart(zone, it.id) }}
      onDragEnd={onDragEnd}
      style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#fff', border: '1px solid #E6E6E6', padding: '9px 11px', cursor: 'grab', opacity: dragging ? 0.4 : 1, transition: 'opacity .15s' }}
    >
      <div style={{ width: 36, height: 36, borderRadius: '50%', flexShrink: 0, background: `#F0F0F0 center/cover no-repeat url("${img(it.p, 100)}")` }} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ fontSize: 12.5, fontWeight: 700, color: '#17264A', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.name}</span>
          <span style={{ padding: '2px 6px', fontSize: 10, fontWeight: 700, background: u.bg, color: u.c, whiteSpace: 'nowrap' }}>{it.dday}</span>
        </div>
        <div style={{ height: 4, background: '#EFEFEF', overflow: 'hidden', marginTop: 5 }}>
          <div style={{ height: '100%', width: it.fresh + '%', background: u.c }} />
        </div>
      </div>
      <span style={{ color: '#C4C4C4', fontSize: 14, cursor: 'grab' }}>⠿</span>
    </div>
  )
}

const zoneGrid: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 8, marginTop: 10, minHeight: 54 }

export default function Fridge() {
  const { data: rows = [], isLoading, error } = usePantryItems()
  const move = usePatchPantryItem()
  const [modal, setModal] = useState<null | 'ocr' | 'add'>(null)
  const [open, setOpen] = useState(false)
  const [drag, setDrag] = useState<{ zone: ZoneKey; id: number } | null>(null)
  const [over, setOver] = useState<ZoneKey | null>(null)
  const overRef = useRef<ZoneKey | null>(null)

  // 서버 행 → zone별 표시 VM (D-day·긴급도·수량표시는 순수 로직에서 파생).
  const zones = useMemo<Zones>(() => {
    const today = new Date()
    const z: Zones = { room: [], fridge: [], freezer: [] }
    for (const r of rows) z[storageToZone(r.storage)].push(toDisplay(r, today))
    return z
  }, [rows])

  const onDragStart = (zone: ZoneKey, id: number) => setDrag({ zone, id })
  const onDragEnd = () => { setDrag(null); setOver(null); overRef.current = null }

  const drop = (to: ZoneKey) => {
    setOver(null); overRef.current = null
    const d = drag
    setDrag(null)
    if (!d || d.zone === to) return
    // #13 보관 위치 이동 → PATCH(storage). 성공 시 pantry 캐시 무효화로 목록 재조회.
    move.mutate({ id: d.id, patch: { storage: zoneToStorage(to) } })
  }

  // 드롭 존 공통 props
  const zoneProps = (key: ZoneKey) => ({
    onDragOver: (e: React.DragEvent) => { e.preventDefault(); if (overRef.current !== key) { overRef.current = key; setOver(key) } },
    onDragLeave: (e: React.DragEvent) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) { if (overRef.current === key) { overRef.current = null; setOver(null) } } },
    onDrop: (e: React.DragEvent) => { e.preventDefault(); drop(key) },
  })
  const hi = (key: ZoneKey): React.CSSProperties => (over === key && drag?.zone !== key ? { outline: '2px dashed #F26419', outlineOffset: 2 } : {})

  const items = (key: ZoneKey) =>
    zones[key].map((it) => <ItemCard key={it.id} it={it} zone={key} dragging={drag?.id === it.id} onDragStart={onDragStart} onDragEnd={onDragEnd} />)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 6 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>내 냉장고</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setModal('ocr')} style={{ padding: '10px 15px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>영수증 스캔</button>
          <button onClick={() => setModal('add')} style={{ padding: '10px 15px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>재료 추가</button>
        </div>
      </div>
      <p style={{ fontSize: 13.5, color: '#5E5E5E', margin: '0 0 18px' }}>재료를 <b>끌어다 칸을 옮겨</b> 정리해요. 유통기한이 임박한 재료는 빨갛게 표시돼요.</p>

      {isLoading && <p style={{ fontSize: 13, color: '#9A9A9A', margin: '0 0 12px' }}>재고를 불러오는 중…</p>}
      {error && (
        <p style={{ fontSize: 13, color: '#F04452', margin: '0 0 12px' }}>
          재고를 불러오지 못했어요: {(error as Error).message}
        </p>
      )}
      {!isLoading && !error && rows.length === 0 && (
        <p style={{ fontSize: 13, color: '#9A9A9A', margin: '0 0 12px' }}>아직 등록한 재료가 없어요. <b>재료 추가</b>로 시작해요.</p>
      )}

      <div style={{ maxWidth: 600, margin: '40px auto 0' }}>
        {/* 실온·팬트리 (드롭 존) */}
        <div {...zoneProps('room')} style={{ background: 'linear-gradient(180deg,#F0EBE2,#E4DCCE)', border: '1px solid #D8CDB8', padding: '14px 18px 16px', boxShadow: '0 6px 16px rgba(0,0,0,.06)', ...hi('room') }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 800, color: '#7A6A48' }}>실온·팬트리</span>
            <span style={{ fontSize: 11, color: '#A99A78' }}>20℃ · 팬트리 선반</span>
            <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: '#A99A78' }}>{zones.room.length}개</span>
          </div>
          <div style={zoneGrid}>{items('room')}</div>
        </div>
        <div style={{ height: 10, background: 'linear-gradient(180deg,#D8CDB8,#CFC3AC)', margin: '0 8px' }} />

        {/* 냉장고 본체 (문 유지 + 3D 스윙) */}
        <div style={{ position: 'relative', perspective: 1800 }}>
          <div style={{ position: 'relative', background: 'linear-gradient(180deg,#EEF1F5,#DFE4EB)', border: '1px solid #C6CDD7', borderRadius: 18, padding: '22px 20px', minHeight: 400, boxShadow: 'inset 0 4px 16px rgba(0,0,0,.08),0 30px 60px rgba(23,38,74,.2)' }}>
            {/* 냉장실 (드롭 존) */}
            <div {...zoneProps('fridge')} style={{ background: 'rgba(255,255,255,.55)', border: '1px solid #D3DAE3', padding: '12px 14px 14px', marginBottom: 14, ...hi('fridge') }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 800, color: '#17264A' }}>냉장실</span>
                <span style={{ fontSize: 11, color: '#9AA3AF' }}>3℃ · 냉장</span>
                <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: '#9AA3AF' }}>{zones.fridge.length}개</span>
              </div>
              <div style={zoneGrid}>{items('fridge')}</div>
            </div>
            {/* 냉동실 (드롭 존) */}
            <div {...zoneProps('freezer')} style={{ background: 'linear-gradient(180deg,#EAF6FF,#CDE8FB)', border: '1px solid #B6D8F0', padding: '12px 14px 14px', ...hi('freezer') }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{ fontSize: 14, fontWeight: 800, color: '#2178AE' }}>냉동실</span>
                <span style={{ fontSize: 11, color: '#6FA6CE' }}>−18℃ · 냉동</span>
                <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: '#6FA6CE' }}>{zones.freezer.length}개</span>
              </div>
              <div style={zoneGrid}>{items('freezer')}</div>
            </div>
            {open && (
              <div onClick={() => setOpen(false)} style={{ position: 'absolute', right: 8, top: 8, zIndex: 23, fontSize: 12.5, fontWeight: 700, color: '#5E5E5E', cursor: 'pointer', border: '1px solid #E6E6E6', padding: '6px 12px', background: '#fff' }}>문 닫기</div>
            )}
          </div>

          {/* 왼쪽 문 */}
          <div onClick={() => !open && setOpen(true)}
            style={{ position: 'absolute', top: 0, left: 0, width: '50%', height: '100%', background: 'linear-gradient(180deg,#EEF1F5,#DBE1E9)', borderRight: '1px solid #CBD2DC', borderRadius: '18px 0 0 18px', transformOrigin: 'left center', transform: open ? 'rotateY(-118deg)' : 'rotateY(0deg)', transition: 'transform .7s cubic-bezier(.45,.05,.2,1)', boxShadow: open ? 'none' : '0 18px 40px rgba(23,38,74,.16)', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', cursor: open ? 'default' : 'pointer', pointerEvents: open ? 'none' : 'auto', zIndex: 6 }}>
            <div style={{ width: 6, height: 170, borderRadius: 3, background: 'linear-gradient(90deg,rgba(0,0,0,.16),rgba(0,0,0,.03))', marginRight: 14 }} />
          </div>
          {/* 오른쪽 문 */}
          <div onClick={() => !open && setOpen(true)}
            style={{ position: 'absolute', top: 0, left: '50%', width: '50%', height: '100%', background: 'linear-gradient(180deg,#EEF1F5,#DBE1E9)', borderRadius: '0 18px 18px 0', transformOrigin: 'right center', transform: open ? 'rotateY(118deg)' : 'rotateY(0deg)', transition: 'transform .7s cubic-bezier(.45,.05,.2,1)', boxShadow: open ? 'none' : '0 18px 40px rgba(23,38,74,.16)', display: 'flex', alignItems: 'center', justifyContent: 'flex-start', cursor: open ? 'default' : 'pointer', pointerEvents: open ? 'none' : 'auto', zIndex: 6 }}>
            <div style={{ width: 6, height: 170, borderRadius: 3, background: 'linear-gradient(270deg,rgba(0,0,0,.16),rgba(0,0,0,.03))', marginLeft: 14 }} />
          </div>

          {/* 닫힘 안내 */}
          <div style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, pointerEvents: 'none', zIndex: 7, opacity: open ? 0 : 1, transition: 'opacity .3s ease' }}>
            <div style={{ background: '#F26419', color: '#fff', fontSize: 13.5, fontWeight: 800, padding: '11px 20px' }}>냉장고 문을 클릭해서 열어보세요</div>
            <span style={{ fontSize: 26, color: '#F26419' }}>▾</span>
          </div>
        </div>
      </div>

      <Modal open={modal === 'ocr'} onClose={() => setModal(null)} title="영수증으로 재고 등록">
        <OcrFlow onDone={() => setModal(null)} />
      </Modal>
      <Modal open={modal === 'add'} onClose={() => setModal(null)} title="재료 직접 등록">
        <FridgeAddForm onDone={() => setModal(null)} />
      </Modal>
    </div>
  )
}
