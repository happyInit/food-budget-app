import { useState } from 'react'
import { Bell } from 'lucide-react'
import { Drawer } from 'vaul'
import { useNavigate } from 'react-router-dom'
import { useIsMobile } from '../../lib/useMediaQuery'
import { notifications } from '../../lib/mock'

const bellClass =
  'relative grid h-10 w-10 place-items-center rounded-xl border border-line bg-surface hover:bg-black/[.03]'

function NotifPanel({ onGo }: { onGo: (to: string) => void }) {
  return (
    <div>
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="font-extrabold">알림</span>
        <button className="text-xs font-semibold text-faint hover:text-sub">모두 읽음</button>
      </div>
      <div className="max-h-[60vh] overflow-y-auto">
        {notifications.map((n) => (
          <button
            key={n.id}
            onClick={() => onGo(n.to)}
            className="flex w-full gap-3 border-b border-line/60 px-4 py-3 text-left hover:bg-black/[.02]"
          >
            <div className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl text-lg ${n.iconBg}`}>
              {n.emoji}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-bold">{n.title}</div>
              <div className="mt-0.5 text-xs text-sub">{n.desc}</div>
              <div className="mt-1 text-[11px] text-faint">{n.time}</div>
            </div>
          </button>
        ))}
      </div>
      <button
        onClick={() => onGo('/notifications')}
        className="w-full py-3.5 text-sm font-bold text-brand hover:bg-brand-weak/50"
      >
        전체 보기
      </button>
    </div>
  )
}

export default function NotificationBell() {
  const isMobile = useIsMobile()
  const [open, setOpen] = useState(false)
  const nav = useNavigate()
  const go = (to: string) => {
    setOpen(false)
    nav(to)
  }
  const dot = <span className="absolute right-2.5 top-2 h-2 w-2 rounded-full bg-danger ring-2 ring-surface" />

  // 모바일: 바텀시트
  if (isMobile) {
    return (
      <Drawer.Root open={open} onOpenChange={setOpen}>
        <Drawer.Trigger className={bellClass} aria-label="알림">
          <Bell size={19} className="text-sub" />
          {dot}
        </Drawer.Trigger>
        <Drawer.Portal>
          <Drawer.Overlay className="fixed inset-0 z-40 bg-black/40" />
          <Drawer.Content className="fixed inset-x-0 bottom-0 z-50 rounded-t-2xl bg-surface outline-none">
            <div className="mx-auto mb-1 mt-3 h-1.5 w-10 rounded-full bg-black/15" />
            <Drawer.Title className="sr-only">알림</Drawer.Title>
            <NotifPanel onGo={go} />
            <div className="h-3" />
          </Drawer.Content>
        </Drawer.Portal>
      </Drawer.Root>
    )
  }

  // 데스크톱: 드롭다운
  return (
    <div className="relative">
      <button className={bellClass} onClick={() => setOpen((o) => !o)} aria-label="알림">
        <Bell size={19} className="text-sub" />
        {dot}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-40 mt-2 w-80 overflow-hidden rounded-2xl border border-line bg-surface shadow-xl">
            <NotifPanel onGo={go} />
          </div>
        </>
      )}
    </div>
  )
}
