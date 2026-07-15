import { useEffect, type ReactNode } from 'react'

// 등록·입력은 전부 오버레이로. variant='center'=중앙 모달, 'sheet'=아래서 위로 덮는 시트.
// 확정본 토큰: backdrop rgba(20,20,20,.5) · z-index 70 · radius 0 · 그림자 0 20px 50px.
type Props = {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
  variant?: 'center' | 'sheet'
  maxWidth?: number
}

export default function Modal({ open, onClose, title, children, variant = 'center', maxWidth = 520 }: Props) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden' // 배경 스크롤 잠금
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, onClose])

  if (!open) return null
  const sheet = variant === 'sheet'

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 70, display: 'flex', alignItems: sheet ? 'flex-end' : 'center', justifyContent: 'center', padding: sheet ? 0 : 16 }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(20,20,20,.5)', animation: 'ovFade .2s ease' }} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{
          position: 'relative',
          background: '#fff',
          width: '100%',
          maxWidth: sheet ? 760 : maxWidth,
          maxHeight: sheet ? '92vh' : 'calc(100vh - 32px)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 20px 50px rgba(0,0,0,.22)',
          animation: sheet ? 'ovSheet .3s cubic-bezier(.32,.72,0,1)' : 'ovPop .22s ease',
        }}
      >
        {sheet && <div style={{ width: 40, height: 4, borderRadius: 2, background: '#D6D6D6', margin: '10px auto 0', flexShrink: 0 }} />}
        {title && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, borderBottom: '1px solid #E6E6E6', padding: sheet ? '12px 20px 14px' : '15px 18px', flexShrink: 0 }}>
            <h2 style={{ fontSize: 17, fontWeight: 800, margin: 0 }}>{title}</h2>
            <button onClick={onClose} aria-label="닫기" style={{ marginLeft: 'auto', width: 30, height: 30, border: 'none', background: '#F4F4F4', color: '#5E5E5E', fontSize: 15, cursor: 'pointer', flexShrink: 0 }}>✕</button>
          </div>
        )}
        <div style={{ padding: sheet ? '18px 22px 26px' : 20, overflowY: 'auto' }}>{children}</div>
      </div>
    </div>
  )
}
