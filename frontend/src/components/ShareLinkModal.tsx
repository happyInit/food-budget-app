import { useEffect, useState, type ReactNode } from 'react'
import Modal from './Modal'
import { copyText } from '../lib/clipboard'

// 공유 링크 복사 모달 — 레시피 상세 공유(#12)·직접작성 발행 완료(#11) 공용.
// 복사는 버튼 클릭(유저 제스처) 안에서 copyText로 실행 → 비-secure/Safari에서도 폴백으로 동작.
export default function ShareLinkModal({
  open, onClose, title = '공유', heading, link,
}: { open: boolean; onClose: () => void; title?: string; heading?: ReactNode; link: string }) {
  const [copied, setCopied] = useState(false)
  // 모달을 다시 열거나 링크가 바뀌면 '복사됨' 상태 초기화.
  useEffect(() => { if (open) setCopied(false) }, [open, link])

  const doCopy = async () => setCopied(await copyText(link))

  return (
    <Modal open={open} onClose={onClose} title={title}>
      {heading && <div style={{ fontSize: 13, color: '#5E5E5E', marginBottom: 10, lineHeight: 1.6 }}>{heading}</div>}
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          readOnly
          value={link}
          onFocus={(e) => e.currentTarget.select()}
          style={{ flex: 1, padding: '10px 12px', border: '1.5px solid #E6E6E6', fontSize: 12.5, outline: 'none', minWidth: 0 }}
        />
        <button
          onClick={doCopy}
          style={{ padding: '0 16px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' }}
        >
          {copied ? '복사됨 ✓' : '복사'}
        </button>
      </div>
      <button
        onClick={() => window.open(link, '_blank', 'noopener,noreferrer')}
        style={{ width: '100%', marginTop: 10, padding: 10, border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}
      >
        새 탭에서 열어보기
      </button>
    </Modal>
  )
}
