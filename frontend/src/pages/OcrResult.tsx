import { useNavigate } from 'react-router-dom'
import { Card, Chip, Button } from '../components/ui'

const rows = [
  { ck: true, raw: '삼겹500', match: '🥩 돼지고기 삼겹살', tag: '매칭', qty: '500g', p: '₩8,900' },
  { ck: true, raw: '대파1단', match: '🧅 대파', tag: '매칭', qty: '1단', p: '₩2,500' },
  { ck: true, raw: '우유OO', match: '서울우유 1L?', tag: '확인', qty: '1개', p: '₩2,980', warn: true },
  { ck: false, raw: '봉투', match: '— 재료 아님', qty: '1', p: '₩100', off: true },
]

export default function OcrResult() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">인식 결과 확인</h1>
          <p className="mt-1 text-sm text-sub">
            잘못 읽은 항목을 고친 뒤 저장하세요. <b>자동 확정되지 않아요.</b>
          </p>
        </div>
        <Chip>GS25 · 07-13 19:24</Chip>
      </div>
      <Card className="mt-5 divide-y divide-line/60">
        {rows.map((r, i) => (
          <div key={i} className={`flex items-center gap-3 px-4 py-3 ${r.warn ? 'bg-warn-weak/20' : ''}`}>
            <input type="checkbox" defaultChecked={r.ck} className="accent-brand" />
            <span className="num w-16 shrink-0 text-xs text-faint">{r.raw}</span>
            <div className={`min-w-0 flex-1 text-sm ${r.off ? 'text-faint' : 'font-bold'}`}>
              {r.match}{' '}
              {r.tag && <Chip tone={r.warn ? 'warn' : 'brand'}>{r.tag}</Chip>}
            </div>
            <span className="num text-xs text-sub">{r.qty}</span>
            <span className="num text-sm font-extrabold">{r.p}</span>
          </div>
        ))}
      </Card>
      <Card className="mt-4 flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <div className="text-[13px] text-sub">냉장고 추가 3건 · 식비 반영</div>
          <div className="num text-xl font-extrabold">₩14,380</div>
        </div>
        <div className="flex gap-2">
          <Button variant="line">다시 촬영</Button>
          <Button onClick={() => nav('/fridge')}>재고·식비에 반영</Button>
        </div>
      </Card>
    </div>
  )
}
