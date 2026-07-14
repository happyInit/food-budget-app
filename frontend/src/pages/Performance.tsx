import { performance as p } from '../lib/mock'
import { Card, Bar } from '../components/ui'

export default function Performance() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">이번 달 성과</h1>
      <p className="mt-1 text-sm text-sub">예산 달성과 식품낭비를 한눈에. 지난달과 비교돼요.</p>
      <div className="mt-5 grid gap-3 md:grid-cols-3">
        {p.stats.map((s) => (
          <Card key={s.k} className="p-5">
            <div className="text-xs font-semibold text-sub">{s.k}</div>
            <div className="mt-1.5 text-2xl font-extrabold text-brand">{s.v}</div>
            {'bar' in s && (
              <div className="my-2">
                <Bar value={(s as { bar: number }).bar} />
              </div>
            )}
            <div className="mt-1 text-[11px] font-semibold text-faint">{s.m}</div>
          </Card>
        ))}
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Card className="p-5">
          <b className="text-[15px]">최근 6개월 식비</b>
          <div className="mt-5 flex h-36 items-end gap-3.5">
            {p.months.map((m) => (
              <div key={m.m} className="flex-1 text-center">
                <div
                  className={`rounded-t-lg ${'now' in m ? 'bg-brand' : 'bg-black/10'}`}
                  style={{ height: m.h + '%' }}
                />
                <div className={`mt-1.5 text-[11px] ${'now' in m ? 'font-extrabold text-brand' : 'text-faint'}`}>
                  {m.m}
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card className="p-5">
          <b className="text-[15px]">재료 활용</b>
          {p.usage.map((u, i) => (
            <div
              key={u.k}
              className={`flex items-center justify-between py-2.5 ${i > 0 ? 'border-t border-line/60' : ''}`}
            >
              <span className="text-sm font-bold">{u.k}</span>
              <span
                className={`num font-extrabold ${
                  u.tone === 'brand' ? 'text-brand' : u.tone === 'danger' ? 'text-danger' : ''
                }`}
              >
                {u.v}
              </span>
            </div>
          ))}
        </Card>
      </div>
    </div>
  )
}
