import type { ReactNode } from 'react'

export default function AuthWrap({ children }: { children: ReactNode }) {
  return (
    <div style={{ minHeight: '100vh', width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24, background: 'linear-gradient(160deg,#F3FBF6 0%,#FFFFFF 60%)' }}>
      <div style={{ width: '100%', maxWidth: 400 }} className="scr-anim">
        {children}
      </div>
    </div>
  )
}

export const inp: React.CSSProperties = { width: '100%', margin: '6px 0 16px', padding: '11px 13px', border: '1.5px solid #E6E6E6', fontSize: 14, outline: 'none', boxSizing: 'border-box' }
export const lab: React.CSSProperties = { fontSize: 12.5, fontWeight: 600, color: '#5E5E5E' }
export const authCard: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 24, boxShadow: '0 2px 10px rgba(0,0,0,.04)' }
export const primaryBtn: React.CSSProperties = { width: '100%', padding: 13, border: 'none', background: '#1FA463', color: '#fff', fontSize: 14.5, fontWeight: 700, cursor: 'pointer' }
