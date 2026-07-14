import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { pantry, img, type PantryItem } from '../lib/data'

const URG = {
  danger: { c: '#F04452', bg: '#FDECEC' },
  warn: { c: '#1FA463', bg: '#E6F6EC' },
  ok: { c: '#15B76E', bg: '#EAF8F0' },
}

function ItemCard({ it }: { it: PantryItem }) {
  const u = URG[it.urg]
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#fff', border: '1px solid #E6E6E6', padding: '9px 11px', cursor: 'grab' }}>
      <div style={{ width: 36, height: 36, borderRadius: '50%', flexShrink: 0, background: `#F0F0F0 center/cover no-repeat url("${img(it.p, 100)}")` }} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ fontSize: 12.5, fontWeight: 700, color: '#1A1A1A', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.name}</span>
          <span style={{ padding: '2px 6px', fontSize: 10, fontWeight: 700, background: u.bg, color: u.c, whiteSpace: 'nowrap' }}>{it.dday}</span>
        </div>
        <div style={{ height: 4, background: '#EFEFEF', overflow: 'hidden', marginTop: 5 }}>
          <div style={{ height: '100%', width: it.fresh + '%', background: u.c }} />
        </div>
      </div>
    </div>
  )
}

const zoneGrid: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 8, marginTop: 10 }

export default function Fridge() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 6 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>내 냉장고</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => nav('/ocr')} style={{ padding: '10px 15px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#1A1A1A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>영수증 스캔</button>
          <button onClick={() => nav('/fridge/add')} style={{ padding: '10px 15px', border: 'none', background: '#1FA463', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>재료 추가</button>
        </div>
      </div>
      <p style={{ fontSize: 13.5, color: '#5E5E5E', margin: '0 0 18px' }}>재료를 끌어다 칸을 옮겨 정리해요. 유통기한이 임박한 재료는 빨갛게 표시돼요.</p>

      <div style={{ maxWidth: 600, margin: '40px auto 0' }}>
        {/* 팬트리 선반 */}
        <div style={{ background: 'linear-gradient(180deg,#F0EBE2,#E4DCCE)', border: '1px solid #D8CDB8', padding: '14px 18px 16px', boxShadow: '0 6px 16px rgba(0,0,0,.06)' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 14, fontWeight: 800, color: '#7A6A48' }}>실온·팬트리</span>
            <span style={{ fontSize: 11, color: '#A99A78' }}>20℃ · 팬트리 선반</span>
            <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: '#A99A78' }}>{pantry.room.length}개</span>
          </div>
          <div style={zoneGrid}>
            {pantry.room.map((it) => <ItemCard key={it.name} it={it} />)}
          </div>
        </div>
        <div style={{ height: 10, background: 'linear-gradient(180deg,#D8CDB8,#CFC3AC)', margin: '0 8px' }} />

        {/* 냉장고 본체 */}
        <div style={{ position: 'relative' }}>
          <div style={{ position: 'relative', background: 'linear-gradient(180deg,#EEF1F5,#DFE4EB)', border: '1px solid #C6CDD7', borderRadius: 18, padding: '22px 20px', minHeight: 400, boxShadow: 'inset 0 4px 16px rgba(0,0,0,.08),0 30px 60px rgba(30,38,52,.2)' }}>
            {open && (
              <>
                <div style={{ background: 'rgba(255,255,255,.55)', border: '1px solid #D3DAE3', padding: '12px 14px 14px', marginBottom: 14 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 800, color: '#1A1A1A' }}>냉장실</span>
                    <span style={{ fontSize: 11, color: '#9AA3AF' }}>3℃ · 냉장</span>
                    <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: '#9AA3AF' }}>{pantry.fridge.length}개</span>
                  </div>
                  <div style={zoneGrid}>{pantry.fridge.map((it) => <ItemCard key={it.name} it={it} />)}</div>
                </div>
                <div style={{ background: 'linear-gradient(180deg,#EAF6FF,#CDE8FB)', border: '1px solid #B6D8F0', padding: '12px 14px 14px' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 800, color: '#2178AE' }}>냉동실</span>
                    <span style={{ fontSize: 11, color: '#6FA6CE' }}>−18℃ · 냉동</span>
                    <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: '#6FA6CE' }}>{pantry.freezer.length}개</span>
                  </div>
                  <div style={zoneGrid}>{pantry.freezer.map((it) => <ItemCard key={it.name} it={it} />)}</div>
                </div>
                <div onClick={() => setOpen(false)} style={{ position: 'absolute', right: 8, top: 8, zIndex: 23, fontSize: 12.5, fontWeight: 700, color: '#5E5E5E', cursor: 'pointer', border: '1px solid #E6E6E6', padding: '6px 12px', background: '#fff' }}>문 닫기</div>
              </>
            )}
          </div>

          {/* 문 (닫힘) */}
          {!open && (
            <div onClick={() => setOpen(true)} style={{ position: 'absolute', inset: 0, cursor: 'pointer', display: 'flex', borderRadius: 18, overflow: 'hidden' }}>
              <div style={{ flex: 1, background: 'linear-gradient(180deg,#EEF1F5,#DBE1E9)', borderRight: '1px solid #CBD2DC', display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
                <div style={{ width: 6, height: 170, borderRadius: 3, background: 'linear-gradient(90deg,rgba(0,0,0,.16),rgba(0,0,0,.03))', marginRight: 14 }} />
              </div>
              <div style={{ flex: 1, background: 'linear-gradient(180deg,#EEF1F5,#DBE1E9)', display: 'flex', alignItems: 'center', justifyContent: 'flex-start' }}>
                <div style={{ width: 6, height: 170, borderRadius: 3, background: 'linear-gradient(270deg,rgba(0,0,0,.16),rgba(0,0,0,.03))', marginLeft: 14 }} />
              </div>
              <div style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, pointerEvents: 'none' }}>
                <div style={{ background: '#1FA463', color: '#fff', fontSize: 13.5, fontWeight: 800, padding: '11px 20px' }}>냉장고 문을 클릭해서 열어보세요</div>
                <span style={{ fontSize: 26, color: '#1FA463' }}>▾</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
