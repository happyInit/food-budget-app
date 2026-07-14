import { Search, ShoppingBag } from 'lucide-react'
import NotificationBell from './NotificationBell'

export default function TopBar({ title }: { title?: string }) {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-cream/90 px-4 backdrop-blur md:h-16 md:px-7">
      {/* 모바일: 로고 */}
      <div className="flex items-center gap-2 md:hidden">
        <img src="/icons/app-icon.png" alt="" className="h-7 w-7 rounded-lg object-cover" />
        <span className="font-extrabold text-brand">{title ?? '밀플래닝'}</span>
      </div>

      {/* 데스크톱: 타이틀 + 검색 */}
      {title && <div className="hidden text-lg font-extrabold md:block">{title}</div>}
      <div className="ml-1 hidden max-w-sm flex-1 items-center gap-2 rounded-full bg-black/[.04] px-4 py-2 text-sm text-faint md:flex">
        <Search size={16} />
        레시피·재료·상품 검색
      </div>

      <div className="ml-auto flex items-center gap-2">
        <NotificationBell />
        <button
          className="grid h-10 w-10 place-items-center rounded-xl border border-line bg-surface hover:bg-black/[.03]"
          aria-label="장바구니"
        >
          <ShoppingBag size={19} className="text-sub" />
        </button>
      </div>
    </header>
  )
}
