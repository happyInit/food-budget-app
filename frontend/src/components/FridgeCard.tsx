import { img } from '../lib/data'
import type { PantryVM, ZoneKey } from '../lib/pantry'

// 냉장고 공유 컴포넌트 — Home(상태 표시 + 관리 CTA)와 Fridge 페이지(⋯ 정리)가 같은 디자인을 쓴다.
// 재료는 칸(실온/냉장/냉동)별 단일 세로 리스트로 "한 줄로 쭉" 이어지게 표시.
const URG = {
  danger: { c: '#F04452', bg: '#FDECEC' },
  warn: { c: '#F26419', bg: '#FCEBDD' },
  ok: { c: '#1E5F96', bg: '#E7EFF8' },
}
const DISPLAY = { fontFamily: 'var(--font-display)' } as const

const ZONES: { key: ZoneKey; label: string; temp: string; tint: string; accent: string }[] = [
  { key: 'room', label: '실온·팬트리', temp: '20℃', tint: 'linear-gradient(180deg,#F7F3EC,#EFE8DC)', accent: '#7A6A48' },
  { key: 'fridge', label: '냉장실', temp: '3℃', tint: '#F4F7FB', accent: '#17264A' },
  { key: 'freezer', label: '냉동실', temp: '−18℃', tint: '#EAF6FF', accent: '#2178AE' },
]

function Row({ it, onAction }: { it: PantryVM; onAction?: (it: PantryVM) => void }) {
  const u = URG[it.urg]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 9, background: '#fff', border: '1px solid #E6E6E6', padding: '7px 10px' }}>
      <div style={{ width: 26, height: 26, borderRadius: '50%', flexShrink: 0, background: `#F0F0F0 center/cover no-repeat url("${img(it.p, 60)}")` }} />
      <span style={{ fontSize: 12.5, fontWeight: 600, color: '#17264A', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1, minWidth: 0 }}>{it.name}</span>
      <span className="num" style={{ padding: '2px 6px', fontSize: 10, fontWeight: 800, background: u.bg, color: u.c, whiteSpace: 'nowrap' }}>{it.dday}</span>
      {onAction && (
        <button
          onClick={() => onAction(it)}
          aria-label={`${it.name} 정리`} title="먹음·버림·삭제"
          style={{ flexShrink: 0, width: 24, height: 24, border: 'none', background: 'transparent', color: '#9A9A9A', fontSize: 17, fontWeight: 800, cursor: 'pointer', lineHeight: 1, padding: 0 }}
        >⋯</button>
      )}
    </div>
  )
}

export default function FridgeCard({ zones, total, mode = 'home', onItemAction, onManage, bodyMaxHeight }: {
  zones: Record<ZoneKey, PantryVM[]>
  total: number
  mode?: 'home' | 'manage'
  onItemAction?: (it: PantryVM) => void   // manage 모드: 재료 ⋯ 클릭
  onManage?: () => void                   // home 모드: 관리하기 CTA
  bodyMaxHeight?: number | string         // home 모드: 이 높이 넘으면 본문 스크롤
}) {
  const filled = total > 0
  return (
    <div style={{ border: '1px solid #C6CDD7', borderRadius: 16, overflow: 'hidden', background: '#F3F5F8', boxShadow: '0 16px 36px rgba(23,38,74,.12)', display: 'flex', flexDirection: 'column' }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 9, background: '#17264A', color: '#fff', padding: '13px 16px', flexShrink: 0 }}>
        <span style={{ ...DISPLAY, fontSize: 17 }}>내 냉장고</span>
        <span style={{ fontSize: 11.5, color: 'rgba(255,255,255,.6)' }}>{filled ? `${total}종 보유` : '비어있어요'}</span>
      </div>

      {/* 본문 — 칸별 단일 리스트. home 모드는 높이 제한 + 스크롤. */}
      <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 12, overflowY: bodyMaxHeight ? 'auto' : 'visible', maxHeight: bodyMaxHeight }}>
        {ZONES.map((z) => {
          const items = zones[z.key]
          return (
            <div key={z.key} style={{ background: z.tint, border: '1px solid rgba(0,0,0,.06)', padding: '10px 12px' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, marginBottom: items.length ? 8 : 0 }}>
                <span style={{ fontSize: 12.5, fontWeight: 800, color: z.accent }}>{z.label}</span>
                <span style={{ fontSize: 10.5, color: '#9AA3AF' }}>{z.temp}</span>
                {items.length > 0 && <span style={{ marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, color: '#9AA3AF' }}>{items.length}개</span>}
              </div>
              {items.length === 0 ? (
                <div style={{ fontSize: 11.5, color: '#B0A99C' }}>비어있어요</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {items.map((it) => <Row key={it.id} it={it} onAction={onItemAction} />)}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* home 모드: 관리하기 CTA */}
      {mode === 'home' && onManage && (
        <div style={{ padding: '0 12px 12px', flexShrink: 0 }}>
          <button onClick={onManage} style={{ width: '100%', padding: 13, border: 'none', background: '#F26419', color: '#fff', ...DISPLAY, fontSize: 15, cursor: 'pointer' }}>
            {filled ? '냉장고 관리하기 →' : '영수증 찍어 채우기'}
          </button>
        </div>
      )}
    </div>
  )
}
