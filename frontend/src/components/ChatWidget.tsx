import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { sendChat, type ChatAction } from '../lib/api'

const DISPLAY = { fontFamily: 'var(--font-display)' } as const

type Msg = { role: 'user' | 'bot'; text: string; actions?: ChatAction[] }

// 챗 서비스는 개인화(냉장고·예산)가 아직 스텁이라, 공용 레시피·가격·영양만 안내한다.
const SEED: Msg[] = [
  { role: 'bot', text: '안녕하세요! 레시피 추천, 재료 가격, 영양 정보를 도와드려요. 무엇이든 물어보세요.' },
]
const QUICK = ['양파 얼마야', '두부로 뭐 해먹지', '김치찌개 레시피']

// 백엔드가 이름 뒤에 붙이는 "… 레시피 보기" 꼬리표 제거 → 카드엔 순수 레시피명만
const cleanName = (label: string) => label.replace(/\s*레시피\s*보기\s*$/, '').replace(/\s*보기\s*$/, '').trim() || label

// 추천 카드가 이름을 대신 보여주므로, 답변 말풍선의 '- 이름' 목록 줄은 숨긴다(중복 제거)
function msgText(m: Msg) {
  if (m.role !== 'bot' || !m.actions?.some((a) => a.action === 'open_recipe')) return m.text
  const kept = m.text.split('\n').filter((l) => !/^\s*[-•]\s/.test(l)).join('\n').trim()
  return kept || m.text
}

export default function ChatWidget({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = useNavigate()
  const [msgs, setMsgs] = useState<Msg[]>(SEED)
  const [text, setText] = useState('')
  const [typing, setTyping] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)   // 멀티턴 세션 — 서버 발급값 유지·재전송
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [msgs, typing, open])

  if (!open) return null

  const send = async (override?: string) => {
    const t = (override ?? text).trim()
    if (!t || typing) return
    setMsgs((m) => [...m, { role: 'user', text: t }])
    setText('')
    setTyping(true)
    try {
      const res = await sendChat(t, sessionId)
      if (res.session_id) setSessionId(res.session_id)   // 멀티턴 ON 시 세션 승계
      // 근거 없는 답(unanswered)엔 액션 버튼을 숨기되, 유튜브 폴백(데이터 없는 음식 안내)은 노출한다.
      const actions = res.unanswered
        ? res.actions?.filter((a) => a.action === 'open_youtube' && a.url)
        : res.actions?.filter((a) => a.action !== 'open_recipe' || a.recipe_id != null)
      setMsgs((m) => [...m, { role: 'bot', text: res.reply, actions: actions?.length ? actions : undefined }])
    } catch {
      setMsgs((m) => [...m, { role: 'bot', text: '지금 어시스턴트에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.' }])
    } finally {
      setTyping(false)
    }
  }

  const goTo = (to: string) => { onClose(); nav(to) }
  const doAction = (a: ChatAction) => {
    if (a.action === 'open_recipe' && a.recipe_id != null) goTo(`/recipes/${a.recipe_id}`)
    else if (a.action === 'add_to_cart') goTo('/cart')
    else if ((a.action === 'open_youtube' || a.action === 'open_url') && a.url) window.open(a.url, '_blank', 'noopener,noreferrer')
    else if (a.action === 'navigate' && a.route) goTo(a.route)   // 기능 안내 딥링크 — 인앱 라우트 이동
  }

  return (
    <div
      role="dialog"
      aria-label="식비 어시스턴트"
      style={{
        position: 'fixed', right: 20, bottom: 96, zIndex: 45,
        width: 'min(360px, calc(100vw - 32px))', height: 'min(540px, calc(100dvh - 150px))',
        background: '#fff', border: '1px solid #E6E6E6', borderRadius: 18, boxShadow: '0 24px 60px rgba(23,38,74,.28)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'chatPop .22s ease',
      }}
    >
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#17264A', color: '#fff', padding: '12px 14px' }}>
        <img src="/icons/app-icon.png" alt="파그" style={{ width: 34, height: 34, borderRadius: '50%', objectFit: 'cover' }} />
        <div style={{ lineHeight: 1.25 }}>
          <div style={{ ...DISPLAY, fontSize: 15 }}>파그 · 식비 어시스턴트</div>
          <div style={{ fontSize: 11, color: 'rgba(255,255,255,.6)', display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#37D67A' }} />온라인
          </div>
        </div>
        <button onClick={onClose} aria-label="닫기" style={{ ...iconBtn, marginLeft: 'auto' }}>✕</button>
      </div>

      {/* 메시지 */}
      <div ref={bodyRef} style={{ flex: 1, padding: 16, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12, background: '#FAFAFA' }}>
        {msgs.map((m, i) => (
          <div key={i} style={{ display: 'contents' }}>
            <div style={{
              alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '82%', fontSize: 13, lineHeight: 1.55, padding: '10px 13px', whiteSpace: 'pre-wrap',
              background: m.role === 'user' ? '#F26419' : '#fff', color: m.role === 'user' ? '#fff' : '#17264A',
              border: m.role === 'user' ? 'none' : '1px solid #ECECEC',
              borderRadius: 16,
            }}>{msgText(m)}</div>
            {m.actions && m.actions.length > 0 && (
              <div style={{ alignSelf: 'flex-start', width: '90%', display: 'flex', flexDirection: 'column', gap: 6 }}>
                {/* 레시피 추천 = 흰 카드(네이비 이름) + 주황 '보기' 버튼 */}
                {m.actions.filter((a) => a.action === 'open_recipe' && a.recipe_id != null).map((a, j) => (
                  <div key={'r' + j} style={recipeCard}>
                    <span style={recipeName}>{cleanName(a.label)}</span>
                    <button onClick={() => doAction(a)} style={viewBtn}>보기</button>
                  </div>
                ))}
                {/* 장바구니 등 그 외 액션 = 주황 아웃라인 */}
                {m.actions.filter((a) => a.action !== 'open_recipe').map((a, j) => (
                  <button key={'o' + j} onClick={() => doAction(a)} style={cartBtn}>{a.label}</button>
                ))}
              </div>
            )}
          </div>
        ))}
        {typing && (
          <div style={{ alignSelf: 'flex-start', background: '#fff', border: '1px solid #ECECEC', borderRadius: 16, padding: '11px 14px', display: 'flex', gap: 4 }}>
            {[0, 1, 2].map((d) => <span key={d} style={{ width: 6, height: 6, borderRadius: '50%', background: '#C4C4C4', animation: `chatDot 1s ${d * 0.15}s infinite` }} />)}
          </div>
        )}
      </div>

      {/* 빠른 질문 */}
      <div className="no-sb" style={{ display: 'flex', gap: 6, padding: '8px 12px 0', overflowX: 'auto' }}>
        {QUICK.map((q) => (
          <button key={q} onClick={() => send(q)} disabled={typing} style={{ flexShrink: 0, padding: '6px 11px', border: '1px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 11.5, fontWeight: 600, cursor: typing ? 'default' : 'pointer', whiteSpace: 'nowrap' }}>{q}</button>
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
        <button onClick={() => send()} aria-label="보내기" style={{ width: 40, height: 40, flexShrink: 0, border: 'none', borderRadius: '50%', background: '#F26419', color: '#fff', fontSize: 15, cursor: 'pointer' }}>↑</button>
      </div>
    </div>
  )
}

const iconBtn: React.CSSProperties = { width: 28, height: 28, border: 'none', background: 'rgba(255,255,255,.14)', color: '#fff', fontSize: 13, cursor: 'pointer', lineHeight: 1 }
// 레시피 추천 카드: 흰 배경 + 네이비 이름(콘텐츠) / 주황 '보기'(CTA)
const recipeCard: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 10, background: '#fff', border: '1px solid #E6E6E6', padding: '9px 11px' }
const recipeName: React.CSSProperties = { flex: 1, minWidth: 0, fontSize: 13, fontWeight: 700, color: '#17264A', lineHeight: 1.35, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }
const viewBtn: React.CSSProperties = { flexShrink: 0, padding: '7px 15px', border: 'none', background: '#F26419', color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer' }
const cartBtn: React.CSSProperties = { alignSelf: 'flex-start', padding: '8px 13px', border: '1px solid #F26419', background: '#fff', color: '#F26419', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }
