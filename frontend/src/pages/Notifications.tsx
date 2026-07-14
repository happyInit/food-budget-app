import { useNavigate } from 'react-router-dom'
import { notifications } from '../lib/mock'
import { Card, Button } from '../components/ui'

export default function Notifications() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-3xl px-4 py-6 md:px-7">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">알림</h1>
          <p className="mt-1 text-sm text-sub">시스템이 밀어주는 이벤트를 모아 보여드려요.</p>
        </div>
        <Button variant="line">모두 읽음</Button>
      </div>
      <Card className="mt-5 divide-y divide-line/60">
        {notifications.map((n) => (
          <button
            key={n.id}
            onClick={() => nav(n.to)}
            className="flex w-full gap-3 px-4 py-4 text-left hover:bg-black/[.02]"
          >
            <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-lg ${n.iconBg}`}>
              {n.emoji}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-bold">{n.title}</div>
              <div className="mt-0.5 text-xs text-sub">{n.desc}</div>
            </div>
            <span className="shrink-0 text-xs text-faint">{n.time}</span>
          </button>
        ))}
      </Card>
    </div>
  )
}
