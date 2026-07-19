import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { sendChat, type ChatAction } from '../lib/api'

type Msg = { role: 'user' | 'bot'; text: string; actions?: ChatAction[] }

const SEED: Msg[] = [
  { role: 'bot', text: '안녕하세요! 레시피 추천, 재료 가격, 영양 정보를 도와드려요. 무엇이든 물어보세요.' },
]
const QUICK = ['양파 얼마야', '두부로 뭐 해먹지', '김치찌개 레시피', '달걀 영양']

export default function Assistant() {
  const nav = useNavigate()
  const [msgs, setMsgs] = useState<Msg[]>(SEED)
  const [text, setText] = useState('')
  const [typing, setTyping] = useState(false)
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [msgs, typing])

  const send = async (override?: string) => {
    const t = (override ?? text).trim()
    if (!t || typing) return
    setMsgs((m) => [...m, { role: 'user', text: t }])
    setText('')
    setTyping(true)
    try {
      const res = await sendChat(t)
      const actions = res.unanswered ? undefined : res.actions?.filter((a) => a.action !== 'open_recipe' || a.recipe_id != null)
      setMsgs((m) => [...m, { role: 'bot', text: res.reply, actions: actions?.length ? actions : undefined }])
    } catch {
      setMsgs((m) => [...m, { role: 'bot', text: '지금 어시스턴트에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.' }])
    } finally {
      setTyping(false)
    }
  }

  const doAction = (a: ChatAction) => {
    if (a.action === 'open_recipe' && a.recipe_id != null) nav(`/recipes/${a.recipe_id}`)
    else if (a.action === 'add_to_cart') nav('/cart')
    else if ((a.action === 'open_youtube' || a.action === 'open_url') && a.url) window.open(a.url, '_blank', 'noopener,noreferrer')
    else if (a.action === 'navigate' && a.route) nav(a.route)
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
        <img src="/icons/app-icon.png" alt="밥풀이" style={{ width: 40, height: 40, borderRadius: '50%', objectFit: 'cover', border: '1px solid #E6E6E6' }} />
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>밥풀이 · 식비 어시스턴트</h1>
        <span style={{ padding: '3px 9px', fontSize: 11, fontWeight: 700, background: '#FCEBDD', color: '#F26419' }}>P1</span>
      </div>
      <div style={{ maxWidth: 680, background: '#fff', border: '1px solid #E6E6E6', overflow: 'hidden', display: 'flex', flexDirection: 'column', height: 560 }}>
        <div ref={bodyRef} style={{ flex: 1, padding: 20, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {msgs.map((m, i) => (
            <div key={i} style={{ display: 'contents' }}>
              <div style={{
                alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '80%', fontSize: 13.5, lineHeight: 1.6, padding: '11px 15px', whiteSpace: 'pre-wrap',
                background: m.role === 'user' ? '#F26419' : '#F7F7F7', color: m.role === 'user' ? '#fff' : '#17264A',
                borderRadius: m.role === 'user' ? '0 14px 4px 14px' : '0 14px 14px 4px',
              }}>{m.text}</div>
              {m.actions && m.actions.length > 0 && (
                <div style={{ alignSelf: 'flex-start', display: 'flex', flexWrap: 'wrap', gap: 8, maxWidth: '85%' }}>
                  {m.actions.map((a, j) => (
                    <button key={j} onClick={() => doAction(a)} style={actionBtn}>{a.label}</button>
                  ))}
                </div>
              )}
            </div>
          ))}
          {typing && (
            <div style={{ alignSelf: 'flex-start', background: '#F7F7F7', borderRadius: '0 14px 14px 4px', padding: '12px 16px', display: 'flex', gap: 5 }}>
              {[0, 1, 2].map((d) => <span key={d} style={{ width: 7, height: 7, borderRadius: '50%', background: '#C4C4C4', animation: `chatDot 1s ${d * 0.15}s infinite` }} />)}
            </div>
          )}
        </div>
        <div className="no-sb" style={{ display: 'flex', gap: 7, padding: '10px 16px 0', overflowX: 'auto' }}>
          {QUICK.map((q) => (
            <button key={q} onClick={() => send(q)} disabled={typing} style={{ flexShrink: 0, padding: '6px 12px', border: '1px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 12, fontWeight: 600, cursor: typing ? 'default' : 'pointer', whiteSpace: 'nowrap' }}>{q}</button>
          ))}
        </div>
        <div style={{ borderTop: '1px solid #E6E6E6', padding: '12px 16px', display: 'flex', gap: 10 }}>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder="무엇이든 물어보세요…"
            style={{ flex: 1, padding: '11px 14px', border: '1.5px solid #E6E6E6', fontSize: 13.5, outline: 'none', minWidth: 0 }}
          />
          <button onClick={() => send()} aria-label="보내기" style={{ width: 42, height: 42, flexShrink: 0, border: 'none', borderRadius: '50%', background: '#F26419', color: '#fff', fontSize: 16, cursor: 'pointer' }}>↑</button>
        </div>
      </div>
    </div>
  )
}

const actionBtn: React.CSSProperties = { padding: '8px 13px', border: '1px solid #F26419', background: '#fff', color: '#F26419', fontSize: 12.5, fontWeight: 700, cursor: 'pointer', lineHeight: 1.3, textAlign: 'left' }
