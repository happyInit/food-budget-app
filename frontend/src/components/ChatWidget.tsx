import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

const DISPLAY = { fontFamily: 'var(--font-display)' } as const

type Card = { name: string; meta: string; to: string }
type Msg = { role: 'user' | 'bot'; text: string; card?: Card }

const SEED: Msg[] = [
  { role: 'bot', text: '안녕하세요! 냉장고 재료·예산에 맞춰 오늘 뭐 해먹을지 도와드려요. 무엇이든 물어보세요 🐶' },
  { role: 'user', text: '냉장고 재료로 3천원 안에 뭐 해먹지?' },
  { role: 'bot', text: '두부(D-1)가 곧 만료돼요! 보유 재료로 만들 수 있는 두부김치를 추천해요. 추가로 대파(1,250원)만 있으면 예산 안에 충분해요.' },
  { role: 'bot', text: '', card: { name: '두부김치', meta: '재료 90% 보유 · 추가 1,250원', to: '/recipes/1' } },
]

// 챗 서비스(#37 RAG) 연동 전까지 임시 응답
function canned(q: string): Msg {
  if (/장바구니|담아|담아줘/.test(q)) return { role: 'bot', text: '대파 1대를 장바구니에 담았어요. 이번 달 예산 잔여는 181,150원이 됩니다.' }
  if (/예산|얼마|남은/.test(q)) return { role: 'bot', text: '7월 남은 예산은 182,400원, 하루 6,080원 쓸 수 있어요. 지금 페이스면 이번 달 여유 있어요.' }
  if (/임박|유통기한|버리/.test(q)) return { role: 'bot', text: '임박 재료는 두부(D-1)·서울우유(D-2)예요. 두부는 두부김치, 우유는 계란찜에 쓰면 딱이에요.' }
  return { role: 'bot', text: '냉장고 재료와 남은 예산을 확인해서 알맞은 메뉴를 찾아볼게요. (RAG 어시스턴트 연동 예정)' }
}

export default function ChatWidget({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate()
  const [msgs, setMsgs] = useState<Msg[]>(SEED)
  const [text, setText] = useState('')
  const [typing, setTyping] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [msgs, typing, open])

  if (!open) return null

  const send = () => {
    const t = text.trim()
    if (!t || typing) return
    setMsgs((m) => [...m, { role: 'user', text: t }])
    setText('')
    setTyping(true)
    window.setTimeout(() => {
      setTyping(false)
      setMsgs((m) => [...m, canned(t)])
    }, 650)
  }

  const goCard = (to: string) => { onClose(); nav(to) }

  return (
    <div
      role="dialog"
      aria-label="식비 어시스턴트"
      style={{
        position: 'fixed', right: 20, bottom: 96, zIndex: 45,
        width: 'min(360px, calc(100vw - 32px))', height: 'min(540px, calc(100dvh - 150px))',
        background: '#fff', border: '1px solid #E6E6E6', boxShadow: '0 24px 60px rgba(23,38,74,.28)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'chatPop .22s ease',
      }}
    >
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#17264A', color: '#fff', padding: '12px 14px' }}>
        <img src="/icons/pug.png" alt="파그" style={{ width: 34, height: 34, borderRadius: '50%', objectFit: 'cover' }} />
        <div style={{ lineHeight: 1.25 }}>
          <div style={{ ...DISPLAY, fontSize: 15 }}>파그 · 식비 어시스턴트</div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,.6)', display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#37D67A' }} />온라인
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          <button onClick={() => goCard('/assistant')} aria-label="전체화면" title="전체화면으로" style={iconBtn}>⤢</button>
          <button onClick={onClose} aria-label="닫기" style={iconBtn}>✕</button>
        </div>
      </div>

      {/* 메시지 */}
      <div ref={bodyRef} style={{ flex: 1, padding: 16, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12, background: '#FAFAFA' }}>
        {msgs.map((m, i) =>
          m.card ? (
            <div key={i} style={{ alignSelf: 'flex-start', maxWidth: '88%', background: '#fff', border: '1px solid #E6E6E6', padding: 11, display: 'flex', gap: 11, alignItems: 'center' }}>
              <div style={{ width: 44, height: 44, background: '#EFEFEF', flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700 }}>{m.card.name}</div>
                <div style={{ fontSize: 11, color: '#9A9A9A' }}>{m.card.meta}</div>
              </div>
              <button onClick={() => goCard(m.card!.to)} style={{ padding: '6px 11px', border: 'none', background: '#F26419', color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>보기</button>
            </div>
          ) : (
            <div key={i} style={{
              alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '82%', fontSize: 13, lineHeight: 1.55, padding: '10px 13px',
              background: m.role === 'user' ? '#F26419' : '#fff', color: m.role === 'user' ? '#fff' : '#17264A',
              border: m.role === 'user' ? 'none' : '1px solid #ECECEC',
              borderRadius: m.role === 'user' ? '12px 12px 3px 12px' : '12px 12px 12px 3px',
            }}>{m.text}</div>
          )
        )}
        {typing && (
          <div style={{ alignSelf: 'flex-start', background: '#fff', border: '1px solid #ECECEC', borderRadius: '12px 12px 12px 3px', padding: '11px 14px', display: 'flex', gap: 4 }}>
            {[0, 1, 2].map((d) => <span key={d} style={{ width: 6, height: 6, borderRadius: '50%', background: '#C4C4C4', animation: `chatDot 1s ${d * 0.15}s infinite` }} />)}
          </div>
        )}
      </div>

      {/* 빠른 질문 */}
      <div className="no-sb" style={{ display: 'flex', gap: 6, padding: '8px 12px 0', overflowX: 'auto' }}>
        {['임박 재료로 추천', '남은 예산 알려줘', '3천원 이하 저녁'].map((q) => (
          <button key={q} onClick={() => { setText(q); }} style={{ flexShrink: 0, padding: '6px 11px', border: '1px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 11.5, fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap' }}>{q}</button>
        ))}
      </div>

      {/* 입력 */}
      <div style={{ padding: 12, display: 'flex', gap: 8 }}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder="무엇이든 물어보세요…"
          style={{ flex: 1, padding: '10px 13px', border: '1.5px solid #E6E6E6', fontSize: 13, outline: 'none', minWidth: 0 }}
        />
        <button onClick={send} aria-label="보내기" style={{ width: 40, height: 40, flexShrink: 0, border: 'none', borderRadius: '50%', background: '#F26419', color: '#fff', fontSize: 15, cursor: 'pointer' }}>↑</button>
      </div>
    </div>
  )
}

const iconBtn: React.CSSProperties = { width: 28, height: 28, border: 'none', background: 'rgba(255,255,255,.14)', color: '#fff', fontSize: 13, cursor: 'pointer', lineHeight: 1 }
