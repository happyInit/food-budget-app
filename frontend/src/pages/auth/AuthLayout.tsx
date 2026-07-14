import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

export default function AuthLayout({
  title,
  sub,
  children,
}: {
  title?: string
  sub?: string
  children: ReactNode
}) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-cream px-5 py-10">
      <div className="w-full max-w-sm">
        <Link to="/" className="mb-8 flex items-center justify-center gap-2">
          <img src="/icons/app-icon.png" alt="" className="h-9 w-9 rounded-xl object-cover" />
          <span className="text-xl font-extrabold text-brand">밀플래닝</span>
        </Link>
        {title && <h1 className="text-2xl font-extrabold tracking-tight">{title}</h1>}
        {sub && <p className="mb-7 mt-1.5 text-sm text-sub">{sub}</p>}
        {children}
      </div>
    </div>
  )
}

export const inputCls =
  'w-full rounded-xl border border-line bg-surface px-4 py-3 text-sm outline-none focus:border-brand focus:ring-2 focus:ring-brand-weak'

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mb-4">
      <label className="mb-1.5 block text-xs font-bold text-sub">{label}</label>
      {children}
    </div>
  )
}
