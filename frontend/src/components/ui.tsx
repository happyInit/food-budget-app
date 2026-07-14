import type { ReactNode } from 'react'

type Tone = 'brand' | 'danger' | 'warn' | 'n'

const chipTone: Record<Tone, string> = {
  brand: 'bg-brand-weak text-brand',
  danger: 'bg-danger-weak text-danger',
  warn: 'bg-warn-weak text-warn',
  n: 'bg-black/5 text-sub',
}

export function Card({
  children,
  className = '',
  onClick,
}: {
  children: ReactNode
  className?: string
  onClick?: () => void
}) {
  return (
    <div onClick={onClick} className={`rounded-2xl border border-line bg-surface shadow-sm ${className}`}>
      {children}
    </div>
  )
}

export function Chip({ children, tone = 'n' }: { children: ReactNode; tone?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-bold ${
        chipTone[tone as Tone] ?? chipTone.n
      }`}
    >
      {children}
    </span>
  )
}

export function Bar({ value }: { value: number }) {
  return (
    <div className="h-2 overflow-hidden rounded-full bg-black/[.07]">
      <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${value}%` }} />
    </div>
  )
}

export function Section({ title, more, onMore }: { title: string; more?: string; onMore?: () => void }) {
  return (
    <div className="mb-3 mt-7 flex items-center justify-between">
      <h2 className="text-base font-extrabold tracking-tight md:text-lg">{title}</h2>
      {more && (
        <button onClick={onMore} className="text-xs font-semibold text-faint hover:text-sub md:text-sm">
          {more}
        </button>
      )}
    </div>
  )
}

export function Thumb({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-black/[.04] text-xl ${className}`}>
      {children}
    </div>
  )
}

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  className = '',
  ...rest
}: {
  children: ReactNode
  variant?: 'primary' | 'ghost' | 'line'
  size?: 'sm' | 'md' | 'lg'
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const v = {
    primary: 'bg-brand text-white hover:bg-brand-dark',
    ghost: 'bg-brand-weak text-brand hover:brightness-95',
    line: 'bg-surface border border-line text-ink hover:bg-black/[.03]',
  }[variant]
  const s = { sm: 'px-3 py-1.5 text-xs', md: 'px-4 py-2.5 text-sm', lg: 'px-5 py-3.5 text-[15px]' }[size]
  return (
    <button className={`inline-flex items-center justify-center gap-1.5 rounded-xl font-bold transition ${v} ${s} ${className}`} {...rest}>
      {children}
    </button>
  )
}
