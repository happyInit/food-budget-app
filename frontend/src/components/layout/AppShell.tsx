import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import BottomNav from './BottomNav'
import TopBar from './TopBar'

// 반응형 앱 셸: 모바일=하단탭 / 데스크톱=사이드바
export default function AppShell({ title }: { title?: string }) {
  return (
    <div className="flex min-h-screen bg-cream">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar title={title} />
        <main className="flex-1 pb-24 md:pb-10">
          <Outlet />
        </main>
      </div>
      <BottomNav />
    </div>
  )
}
