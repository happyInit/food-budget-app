import { NavLink } from 'react-router-dom'
import { NAV } from '../../lib/nav'

export default function BottomNav() {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t border-line bg-surface/95 px-1 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
      {NAV.map(({ to, label, Icon }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            `flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-semibold ${
              isActive ? 'text-brand' : 'text-faint'
            }`
          }
        >
          <Icon size={22} strokeWidth={1.9} />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}
