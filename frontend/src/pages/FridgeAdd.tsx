import { useNavigate } from 'react-router-dom'
import { Card, Button } from '../components/ui'
import { inputCls, Field } from './auth/AuthLayout'

export default function FridgeAdd() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">재료 직접 추가</h1>
      <p className="mt-1 text-sm text-sub">표준 재료명으로 자동완성돼요. 기존 재고도 여기서 수정·삭제할 수 있어요.</p>
      <div className="mt-5 grid gap-4 md:grid-cols-[380px_1fr] md:items-start">
        <Card className="p-5">
          <Field label="재료명">
            <input className={inputCls} defaultValue="애호박" />
            <div className="mt-1.5 text-[11px] text-faint">표준 품목: 애호박 · 호박류</div>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="수량">
              <input className={inputCls} defaultValue="1개" />
            </Field>
            <Field label="보관">
              <select className={inputCls}>
                <option>냉장</option>
                <option>냉동</option>
                <option>실온</option>
              </select>
            </Field>
          </div>
          <Field label="유통기한">
            <input className={inputCls} type="date" />
          </Field>
          <Button size="lg" className="w-full" onClick={() => nav('/fridge')}>
            추가하기
          </Button>
        </Card>
        <Card>
          <div className="border-b border-line px-4 py-3.5 font-extrabold">최근 추가</div>
          {[
            ['🥬 애호박', '1개 · 냉장', '방금'],
            ['🧄 다진마늘', '100g · 냉장', '어제'],
            ['🥚 계란', '10구 · 냉장', '2일 전'],
          ].map(([n, q, t]) => (
            <div key={n} className="flex items-center gap-3 border-b border-line/60 px-4 py-3 last:border-0">
              <div className="flex-1 text-sm font-bold">{n}</div>
              <span className="num text-xs text-sub">{q}</span>
              <span className="text-xs text-faint">{t}</span>
            </div>
          ))}
        </Card>
      </div>
    </div>
  )
}
