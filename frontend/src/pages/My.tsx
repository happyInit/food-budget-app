import { useNavigate } from 'react-router-dom'
import { Card } from '../components/ui'

export default function My() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-3xl px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">설정</h1>
      <Card className="mt-5 flex items-center gap-4 p-5">
        <div className="grid h-14 w-14 place-items-center rounded-full bg-brand-weak text-xl font-extrabold text-brand">
          봉
        </div>
        <div>
          <div className="text-[17px] font-extrabold">김봉수</div>
          <div className="text-[13px] text-sub">bravo@meal.kr · 월 예산 ₩460,000</div>
        </div>
        <button className="ml-auto rounded-lg border border-line px-3 py-1.5 text-xs font-bold">프로필 편집</button>
      </Card>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Card>
          <div className="border-b border-line px-4 py-3.5 font-extrabold">예산 · 추천</div>
          {[
            ['월 예산 설정', '₩460,000'],
            ['제외 재료', '오이 · 가지'],
            ['알림 설정', '최저가·임박 on'],
          ].map(([a, b]) => (
            <div
              key={a}
              className="flex items-center justify-between border-b border-line/60 px-4 py-3.5 last:border-0"
            >
              <div className="text-sm font-bold">{a}</div>
              <span className="text-xs text-sub">{b} ›</span>
            </div>
          ))}
        </Card>
        <Card>
          <div className="border-b border-line px-4 py-3.5 font-extrabold">계정</div>
          <button
            onClick={() => nav('/recipebook')}
            className="flex w-full items-center justify-between border-b border-line/60 px-4 py-3.5 text-left text-sm font-bold"
          >
            내 레시피북 <span className="text-faint">›</span>
          </button>
          <div className="flex items-center justify-between border-b border-line/60 px-4 py-3.5 text-sm font-bold">
            로그인 정보 <span className="text-faint">›</span>
          </div>
          <button
            onClick={() => nav('/')}
            className="flex w-full items-center justify-between px-4 py-3.5 text-left text-sm font-bold text-danger"
          >
            로그아웃 <span className="text-faint">›</span>
          </button>
        </Card>
      </div>
    </div>
  )
}
