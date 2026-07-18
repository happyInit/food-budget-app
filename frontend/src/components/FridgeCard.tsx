import { useState } from 'react'
import {
  DndContext, PointerSensor, TouchSensor, useDraggable, useDroppable, useSensor, useSensors,
  pointerWithin, type DragEndEvent,
} from '@dnd-kit/core'
import { emojiForItem } from '../lib/emoji'
import { zoneToStorage, type PantryVM, type ZoneKey } from '../lib/pantry'
import type { Storage } from '../lib/types'

// 냉장고 공유 컴포넌트 — Home(문 달린 상태 카드 + 관리 CTA)와 Fridge 페이지(문 열림 + ⋯ 정리)가 같은 디자인.
// 재료는 칸별 단일 세로 리스트("한 줄로 쭉"). 카드는 부모 높이를 꽉 채움(height:100%).
// manage 모드(onItemDrop 제공)에선 재료를 다른 칸으로 드래그해 보관구역을 옮길 수 있다(#3, @dnd-kit).
const URG = {
  danger: { c: '#F04452', bg: '#FDECEC' },
  warn: { c: '#F26419', bg: '#FCEBDD' },
  ok: { c: '#1E5F96', bg: '#E7EFF8' },
}
const DISPLAY = { fontFamily: 'var(--font-display)' } as const

function MiniChip({ it, onAction }: { it: PantryVM; onAction?: (it: PantryVM) => void }) {
  const u = URG[it.urg]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: '#fff', border: '1px solid #E6E6E6', padding: '6px 9px' }}>
      <span aria-hidden style={{ width: 24, height: 24, borderRadius: '50%', flexShrink: 0, background: '#F0F0F0', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, lineHeight: 1 }}>{emojiForItem(it.name)}</span>
      <span style={{ fontSize: 12, fontWeight: 600, color: '#17264A', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1, minWidth: 0 }}>{it.name}</span>
      <span className="num" style={{ padding: '1px 6px', fontSize: 10, fontWeight: 800, background: u.bg, color: u.c, whiteSpace: 'nowrap' }}>{it.dday}</span>
      {onAction && (
        <button
          onClick={() => onAction(it)}
          onPointerDown={(e) => e.stopPropagation()}   // 드래그 리스너로 이벤트가 새지 않게 — ⋯는 항상 클릭
          aria-label={`${it.name} 정리`} title="먹음·버림·삭제"
          style={{ flexShrink: 0, width: 22, height: 22, border: 'none', background: 'transparent', color: '#9A9A9A', fontSize: 16, fontWeight: 800, cursor: 'pointer', lineHeight: 1, padding: 0 }}
        >⋯</button>
      )}
    </div>
  )
}

// 드래그 가능한 재료 칩(manage 모드). 누른 채 8px 이동(또는 터치 짧게 홀드)해야 드래그 시작 → 스크롤·⋯클릭과 구분.
function DragChip({ it, onAction }: { it: PantryVM; onAction?: (it: PantryVM) => void }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({ id: it.id, data: { zone: it.zone } })
  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      style={{
        transform: transform ? `translate3d(${transform.x}px,${transform.y}px,0)` : undefined,
        opacity: isDragging ? 0.4 : 1, touchAction: 'none', cursor: 'grab',
        position: 'relative', zIndex: isDragging ? 30 : undefined,
      }}
    >
      <MiniChip it={it} onAction={onAction} />
    </div>
  )
}

// 냉장고 한 칸(냉장/냉동) — 남는 높이를 flex 로 채우고, 재료 많으면 내부 스크롤. dnd면 드롭 타깃.
function Compartment({ label, temp, tint, accent, items, onAction, zone, dnd }: {
  label: string; temp: string; tint: string; accent: string; items: PantryVM[]
  onAction?: (it: PantryVM) => void; zone: ZoneKey; dnd: boolean
}) {
  const { setNodeRef, isOver } = useDroppable({ id: zone, disabled: !dnd })
  return (
    <div ref={setNodeRef} style={{ background: tint, border: '1px solid rgba(0,0,0,.06)', outline: dnd && isOver ? '2px dashed #F26419' : undefined, outlineOffset: -2, padding: '10px 12px', flex: 1, minHeight: 92, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, marginBottom: 8, flexShrink: 0 }}>
        <span style={{ fontSize: 12.5, fontWeight: 800, color: accent }}>{label}</span>
        <span style={{ fontSize: 10.5, color: '#9AA3AF' }}>{temp}</span>
        {items.length > 0 && <span style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, color: '#9AA3AF' }}>{items.length}개</span>}
      </div>
      {items.length === 0 ? (
        <div style={{ fontSize: 11.5, color: '#9AA3AF' }}>{dnd && isOver ? '여기로 옮기기' : '비어있어요'}</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, overflowY: 'auto' }}>
          {items.map((it) => (dnd ? <DragChip key={it.id} it={it} onAction={onAction} /> : <MiniChip key={it.id} it={it} onAction={onAction} />))}
        </div>
      )}
    </div>
  )
}

export default function FridgeCard({ zones, total, mode = 'home', onItemAction, onManage, onItemDrop }: {
  zones: Record<ZoneKey, PantryVM[]>
  total: number
  mode?: 'home' | 'manage'
  onItemAction?: (it: PantryVM) => void   // manage 모드: 재료 ⋯ 클릭
  onManage?: () => void                   // home 모드: 관리하기 CTA
  onItemDrop?: (id: number, storage: Storage) => void  // manage 모드: 드래그로 보관구역 이동(#3)
}) {
  const [doorOpen, setDoorOpen] = useState(false)
  const dnd = mode === 'manage' && !!onItemDrop
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 8 } }),
  )
  const roomDrop = useDroppable({ id: 'room', disabled: !dnd })
  const onDragEnd = (e: DragEndEvent) => {
    const to = e.over?.id as ZoneKey | undefined
    const from = e.active.data.current?.zone as ZoneKey | undefined
    if (to && from && to !== from) onItemDrop?.(Number(e.active.id), zoneToStorage(to))
  }

  const filled = total > 0
  const withDoors = true                  // Home·Fridge 완전 동일 — 둘 다 문 달림(닫힘 기본, 클릭해서 열기).
  // 내 냉장고(manage): 열어도 문이 사라지지 않게 — 본체 내용을 안쪽으로 밀고 문을 좌우 세로 패널로 세운다.
  //   (Home 은 기존대로 문이 활짝 젖혀지며 열림 — 상태 미리보기 카드라 내용 조작이 없음.)
  const sideOpen = mode === 'manage' && doorOpen
  const doorFace: React.CSSProperties = {
    position: 'absolute', top: 12, bottom: 12, width: 'calc(50% - 14px)',
    background: 'linear-gradient(180deg,#EEF1F5,#DBE1E9)',
    transition: 'transform .7s cubic-bezier(.45,.05,.2,1), width .5s cubic-bezier(.45,.05,.2,1), box-shadow .5s ease',
    boxShadow: doorOpen ? 'none' : '0 14px 30px rgba(23,38,74,.14)',
    display: 'flex', alignItems: 'center', cursor: doorOpen ? 'default' : 'pointer',
    pointerEvents: doorOpen ? 'none' : 'auto', zIndex: 6,
  }

  const card = (
    <div style={{ border: '1px solid #C6CDD7', borderRadius: 16, overflow: 'hidden', background: 'linear-gradient(180deg,#EEF1F5,#DFE4EB)', boxShadow: '0 20px 44px rgba(23,38,74,.14)', height: '100%', minHeight: 460, display: 'flex', flexDirection: 'column' }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 9, background: '#17264A', color: '#fff', padding: '13px 16px', flexShrink: 0 }}>
        <span style={{ ...DISPLAY, fontSize: 17 }}>내 냉장고</span>
        <span style={{ fontSize: 11.5, color: 'rgba(255,255,255,.6)' }}>{filled ? `${total}종 보유` : '비어있어요'}</span>
        {withDoors && doorOpen && (
          <span onClick={() => setDoorOpen(false)} style={{ marginLeft: 'auto', fontSize: 11.5, fontWeight: 700, color: '#fff', cursor: 'pointer', border: '1px solid rgba(255,255,255,.32)', padding: '4px 10px' }}>문 닫기</span>
        )}
      </div>

      {/* 실온·팬트리 = 문 밖 선반(항상 보임) · dnd면 드롭 타깃 */}
      <div ref={dnd ? roomDrop.setNodeRef : undefined} style={{ background: 'linear-gradient(180deg,#F0EBE2,#E4DCCE)', borderBottom: '1px solid #D8CDB8', outline: dnd && roomDrop.isOver ? '2px dashed #F26419' : undefined, outlineOffset: -3, padding: '11px 14px 13px', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, marginBottom: zones.room.length ? 8 : 0 }}>
          <span style={{ fontSize: 12.5, fontWeight: 800, color: '#7A6A48' }}>실온·팬트리</span>
          <span style={{ fontSize: 10.5, color: '#A99A78' }}>20℃ · 팬트리 선반</span>
          {zones.room.length > 0 && <span style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, color: '#A99A78' }}>{zones.room.length}개</span>}
        </div>
        {zones.room.length === 0 ? (
          <div style={{ fontSize: 11.5, color: '#BBA97F' }}>{dnd && roomDrop.isOver ? '여기로 옮기기' : '비어있어요'}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {zones.room.map((it) => (dnd ? <DragChip key={it.id} it={it} onAction={onItemAction} /> : <MiniChip key={it.id} it={it} onAction={onItemAction} />))}
          </div>
        )}
      </div>
      {/* 선반–본체 사이 나무 단 */}
      <div style={{ height: 8, background: 'linear-gradient(180deg,#D8CDB8,#CFC3AC)', flexShrink: 0 }} />

      {/* 냉장고 본체: 냉장·냉동 칸 (+ home 은 문) — 남는 높이를 flex 로 채움 */}
      <div style={{ position: 'relative', perspective: 1600, padding: 14, flex: 1, display: 'flex' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, flex: 1, minWidth: 0, marginLeft: sideOpen ? 40 : 0, marginRight: sideOpen ? 40 : 0, transition: 'margin .5s cubic-bezier(.45,.05,.2,1)' }}>
          <Compartment label="냉장실" temp="3℃" tint="rgba(255,255,255,.6)" accent="#17264A" items={zones.fridge} onAction={onItemAction} zone="fridge" dnd={dnd} />
          <Compartment label="냉동실" temp="−18℃" tint="#EAF6FF" accent="#2178AE" items={zones.freezer} onAction={onItemAction} zone="freezer" dnd={dnd} />
        </div>

        {withDoors && (
          <>
            {/* 왼쪽 문 — manage 열림(sideOpen): 좌측 세로 패널로 남음 / 그 외: 활짝 젖혀 열림 */}
            <div onClick={() => !doorOpen && setDoorOpen(true)}
              style={{ ...doorFace, left: 14,
                width: sideOpen ? 32 : 'calc(50% - 14px)',
                borderRight: '1px solid #CBD2DC', borderRadius: '10px 0 0 10px', justifyContent: 'flex-end',
                transformOrigin: 'left center',
                transform: sideOpen ? 'rotateY(-24deg)' : doorOpen ? 'rotateY(-118deg)' : 'rotateY(0deg)',
                boxShadow: sideOpen ? '3px 6px 14px rgba(23,38,74,.18)' : doorFace.boxShadow }}>
              <div style={{ width: 5, height: 96, borderRadius: 3, background: 'linear-gradient(90deg,rgba(0,0,0,.16),rgba(0,0,0,.03))', marginRight: sideOpen ? 6 : 12 }} />
            </div>
            {/* 오른쪽 문 */}
            <div onClick={() => !doorOpen && setDoorOpen(true)}
              style={{ ...doorFace, right: 14,
                width: sideOpen ? 32 : 'calc(50% - 14px)',
                borderRadius: '0 10px 10px 0', justifyContent: 'flex-start',
                transformOrigin: 'right center',
                transform: sideOpen ? 'rotateY(24deg)' : doorOpen ? 'rotateY(118deg)' : 'rotateY(0deg)',
                boxShadow: sideOpen ? '-3px 6px 14px rgba(23,38,74,.18)' : doorFace.boxShadow }}>
              <div style={{ width: 5, height: 96, borderRadius: 3, background: 'linear-gradient(270deg,rgba(0,0,0,.16),rgba(0,0,0,.03))', marginLeft: sideOpen ? 6 : 12 }} />
            </div>
            {/* 닫힘 안내 */}
            <div style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, pointerEvents: 'none', zIndex: 7, opacity: doorOpen ? 0 : 1, transition: 'opacity .3s ease' }}>
              <div style={{ background: '#F26419', color: '#fff', fontSize: 12.5, fontWeight: 800, padding: '9px 16px', textAlign: 'center' }}>냉장고 문을 클릭해서 열어보세요</div>
              <span style={{ fontSize: 22, color: '#F26419' }}>▾</span>
            </div>
          </>
        )}
      </div>

      {/* home 모드: 관리하기 CTA */}
      {mode === 'home' && onManage && (
        <div style={{ padding: '0 14px 14px', flexShrink: 0 }}>
          <button onClick={onManage} style={{ width: '100%', padding: 13, border: 'none', background: '#F26419', color: '#fff', ...DISPLAY, fontSize: 15, cursor: 'pointer' }}>
            {filled ? '냉장고 관리하기 →' : '영수증 찍어 채우기'}
          </button>
        </div>
      )}
    </div>
  )

  // DnD 컨텍스트로 감싼다 — Home은 dnd=false라 드롭 비활성·드래그 없음(무동작). 항상 감싸 컨텍스트 밖 hook 사용을 피함.
  // 충돌감지 = pointerWithin(포인터 기준): 얇은 실온·팬트리 선반도 포인터만 올리면 드롭 타깃이 됨
  //   (기본 rectIntersection 은 겹침 면적으로 판정 → 얇은 실온 선반이 큰 냉장/냉동 칸에 밀려 드롭 불가였음)
  return <DndContext sensors={sensors} collisionDetection={pointerWithin} onDragEnd={onDragEnd}>{card}</DndContext>
}
