import { NavLink } from 'react-router-dom'
import { NAV } from '../../lib/nav'

export default function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-surface px-3 py-5 md:flex">
      <div className="flex items-center gap-2 px-3 pb-5">
        <img src="/icons/app-icon.png" alt="밀플래닝" className="h-8 w-8 rounded-lg object-cover" />
        <span className="text-lg font-extrabold tracking-tight text-brand">밀플래닝</span>
      </div>
      <nav className="flex flex-col gap-1">
        {NAV.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold ${
                isActive ? 'bg-brand-weak text-brand' : 'text-sub hover:bg-black/[.03]'
              }`
            }
          >
            <Icon size={19} />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
