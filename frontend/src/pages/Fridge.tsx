import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Camera, Pencil } from 'lucide-react'
import { fridgeData } from '../lib/mock'
import { Card, Chip, Section, Thumb, Button } from '../components/ui'

export default function Fridge() {
  const nav = useNavigate()
  const [filter, setFilter] = useState(0)
  const d = fridgeData

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">내 냉장고</h1>
          <p className="mt-1 text-sm text-sub">영수증 OCR·수동입력으로 재고를 관리해요.</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => nav('/ocr')}>
            <Camera size={16} /> 영수증 OCR
          </Button>
          <Button variant="line" onClick={() => nav('/fridge/add')}>
            <Pencil size={16} /> 직접 추가
          </Button>
        </div>
      </div>

      {/* 요약 */}
      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {d.summary.map((s) => (
          <Card key={s.k} className="p-4">
            <div className="text-xs font-semibold text-sub">{s.k}</div>
            <div className={`num mt-1.5 text-2xl font-extrabold ${s.tone === 'danger' ? 'text-danger' : ''}`}>
              {s.v}
              <span className="text-sm text-faint">{s.unit}</span>
            </div>
            <div
              className={`mt-1 text-[11px] font-semibold ${
                s.tone === 'danger' ? 'text-danger' : s.tone === 'brand' ? 'text-brand' : 'text-faint'
              }`}
            >
              {s.m}
            </div>
          </Card>
        ))}
      </div>

      {/* 임박 */}
      <Section title="유통기한 임박" more="🔔 알림 연동" />
      <div className="grid gap-3 md:grid-cols-2">
        {d.expiring.map((e) => (
          <Card
            key={e.name}
            className={`p-4 ${e.tone === 'danger' ? 'border-danger-weak bg-danger-weak/30' : 'border-warn-weak bg-warn-weak/30'}`}
          >
            <div className="flex items-center gap-3">
              <Thumb className={e.tone === 'danger' ? 'bg-danger-weak' : 'bg-warn-weak'}>{e.emoji}</Thumb>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 font-bold">
                  {e.name} <Chip tone={e.tone}>{e.dday}</Chip>
                </div>
                <div className="text-xs text-sub">{e.sub}</div>
              </div>
              <Button variant="ghost" size="sm">
                쓸 레시피
              </Button>
            </div>
          </Card>
        ))}
      </div>

      {/* 재고 목록 */}
      <Section title="재고 목록" />
      <div className="mb-3 flex gap-2 overflow-x-auto">
        {d.filters.map((f, i) => (
          <button
            key={f}
            onClick={() => setFilter(i)}
            className={`shrink-0 rounded-full border px-4 py-2 text-sm font-bold ${
              filter === i ? 'border-ink bg-ink text-white' : 'border-line bg-surface text-sub'
            }`}
          >
            {f}
          </button>
        ))}
      </div>
      <Card>
        {d.stock.map((s, i) => (
          <div key={i} className={`flex items-center gap-3 px-4 py-3 ${i > 0 ? 'border-t border-line/60' : ''}`}>
            <Thumb>{s.emoji}</Thumb>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-bold">{s.name}</div>
              <div className="num text-xs text-sub">
                {s.qty} · {s.place}
              </div>
            </div>
            <Chip tone={s.tone}>{s.dday}</Chip>
            <button className="text-xs font-semibold text-faint hover:text-sub">수정</button>
          </div>
        ))}
      </Card>
    </div>
  )
}
