import { useNavigate } from 'react-router-dom'
import { expense as e } from '../lib/mock'
import { Card, Thumb, Button } from '../components/ui'

const WD = ['월', '화', '수', '목', '금', '토', '일']

export default function Expense() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">식비 관리</h1>
          <p className="mt-1 text-sm text-sub">날짜를 누르면 그날 지출이 열려요.</p>
        </div>
        <Button variant="line" onClick={() => nav('/expense/add')}>
          ＋ 지출 추가
        </Button>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ['7월 예산', '₩' + e.budget, '남은 12일'],
          ['누적 지출', '₩' + e.spent, e.percent + '% 사용'],
          ['장보기 / 외식', '193k / 84k', '배달 ₩0'],
          ['남은 예산', '₩' + e.remaining, '순항 중'],
        ].map(([k, v, m]) => (
          <Card key={k} className="p-4">
            <div className="text-xs font-semibold text-sub">{k}</div>
            <div className="num mt-1.5 text-xl font-extrabold">{v}</div>
            <div className="mt-1 text-[11px] font-semibold text-faint">{m}</div>
          </Card>
        ))}
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-[1fr_320px] md:items-start">
        <Card className="p-5">
          <div className="mb-3.5 flex items-center justify-between">
            <b>2026년 7월</b>
            <span className="text-faint">‹ ›</span>
          </div>
          <div className="grid grid-cols-7 gap-1.5">
            {WD.map((w) => (
              <div key={w} className="py-1 text-center text-[11px] font-bold text-faint">
                {w}
              </div>
            ))}
            {e.days.map((d, i) => (
              <div
                key={i}
                className={`relative aspect-square rounded-lg border p-1.5 text-[12.5px] font-bold ${
                  d.today
                    ? 'border-brand bg-brand-weak/40'
                    : d.hot
                      ? 'border-[#f4dede] bg-[#fff7f7]'
                      : 'border-line/60'
                }`}
              >
                {d.d}
                {d.sp && (
                  <span className="num absolute bottom-1.5 left-1.5 text-[10px] font-extrabold text-danger">
                    {d.sp}
                  </span>
                )}
              </div>
            ))}
          </div>
        </Card>
        <Card className="p-5">
          <div className="font-extrabold">7월 12일 (오늘)</div>
          <div className="num mb-3 text-2xl font-extrabold">₩9,000</div>
          {e.today.map((t, i) => (
            <div key={i} className={`flex items-center gap-3 py-2.5 ${i > 0 ? 'border-t border-line/60' : ''}`}>
              <Thumb>{t.icon}</Thumb>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-bold">{t.t}</div>
                <div className="text-xs text-sub">{t.s}</div>
              </div>
              <span className="num text-sm font-extrabold">{t.p}</span>
            </div>
          ))}
        </Card>
      </div>
    </div>
  )
}
