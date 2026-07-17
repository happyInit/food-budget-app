import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useOcrJob, useConfirmReceipt } from '../lib/queries'
import type { OcrItem, PantryStorage, ReceiptConfirmResult } from '../lib/api'
import { won } from '../lib/api'

const th: React.CSSProperties = { textAlign: 'left', padding: '8px 8px', borderBottom: '2px solid #E6E6E6', fontSize: 11.5, color: '#5E5E5E', fontWeight: 600, whiteSpace: 'nowrap' }
const cell: React.CSSProperties = { padding: '8px 8px', borderBottom: '1px solid #EFEFEF', verticalAlign: 'middle' }
const inp: React.CSSProperties = { padding: '6px 8px', border: '1.5px solid #E6E6E6', fontSize: 12.5, outline: 'none', width: '100%', boxSizing: 'border-box' }

const CATS = ['식재료', '가공식품', '비식품', '조정'] as const
const STORAGES: { v: PantryStorage; label: string }[] = [
  { v: 'ROOM', label: '실온' }, { v: 'FRIDGE', label: '냉장' }, { v: 'FREEZER', label: '냉동' },
]
const isPantryCat = (c: string | null) => c !== '비식품' && c !== '조정'

type Row = {
  raw_text: string | null
  name: string
  item_id: number | null
  quantity: string | null
  price: number | null
  is_food: boolean
  category: string | null
  storage: PantryStorage | null
  expire_at: string       // '' | 'YYYY-MM-DD'
  keep: boolean
  needs_review: boolean
}

function toRow(it: OcrItem): Row {
  return {
    raw_text: it.raw_text, name: it.name ?? '', item_id: it.item_id, quantity: it.quantity,
    price: it.price, is_food: it.is_food, category: it.category, storage: it.storage,
    expire_at: '', keep: isPantryCat(it.category) && it.storage != null, needs_review: it.needs_review,
  }
}

export default function OcrResult() {
  const nav = useNavigate()
  const [sp] = useSearchParams()
  const jobId = sp.get('job')
  const { data, error } = useOcrJob(jobId)
  const confirm = useConfirmReceipt()

  const [rows, setRows] = useState<Row[] | null>(null)
  const seeded = useRef(false)
  const [result, setResult] = useState<ReceiptConfirmResult & { expenseRecorded: boolean } | null>(null)
  const [formErr, setFormErr] = useState<string | null>(null)

  useEffect(() => {
    if (data?.status === 'DONE' && !seeded.current) {
      seeded.current = true
      setRows(data.items.map(toRow))
    }
  }, [data])

  const patch = (i: number, p: Partial<Row>) =>
    setRows((rs) => (rs ? rs.map((r, idx) => (idx === i ? { ...r, ...p } : r)) : rs))

  const onCategory = (i: number, c: string) =>
    patch(i, isPantryCat(c)
      ? { category: c, keep: true, storage: rows?.[i].storage ?? 'FRIDGE' }
      : { category: c, keep: false })

  // ── 상태별 화면 ──
  if (!jobId) return <Notice title="잘못된 접근" body="업로드부터 다시 시작해 주세요." onBack={() => nav('/ocr')} />
  if (error) return <Notice title="결과를 불러오지 못했어요" body={error.message} onBack={() => nav('/ocr')} />
  if (!data || data.status === 'PENDING') return <Analyzing />
  if (data.status === 'FAILED') return <Notice title="인식에 실패했어요" body={data.reason ?? '다시 시도해 주세요.'} onBack={() => nav('/ocr')} />

  // 성공 요약
  if (result)
    return (
      <div>
        <h1 style={{ fontSize: 23, fontWeight: 800, margin: '0 0 16px' }}>등록 완료</h1>
        <div style={{ background: '#E7F5EC', border: '1px solid #BCE3C9', padding: 20, marginBottom: 16 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#1B7A46', marginBottom: 8 }}>냉장고에 {result.added_count}개 재료를 담았어요</div>
          <div style={{ fontSize: 13, color: '#2E7D4F' }}>
            식비 <b>{won(result.expense_amount)}원</b>
            {result.expenseRecorded ? ' 을(를) 식비 캘린더에 기록했어요.' : ' 계산은 됐지만 캘린더 기록에 실패했어요. 식비에서 직접 추가해 주세요.'}
          </div>
          {result.needs_expense_review && (
            <div style={{ fontSize: 12, color: '#B26A00', marginTop: 8 }}>⚠ 영수증 합계와 항목 금액이 정확히 맞지 않아요. 식비 금액을 확인해 주세요.</div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => nav('/pantry')} style={{ padding: '11px 18px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>냉장고로 가기 →</button>
          <button onClick={() => nav('/ocr')} style={{ padding: '11px 18px', border: '1.5px solid #E6E6E6', background: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>영수증 더 올리기</button>
        </div>
      </div>
    )

  // ── DONE: HITL 편집표 ──
  const list = rows ?? []
  const nonfoodSum = list.filter((r) => r.category === '비식품').reduce((s, r) => s + (r.price ?? 0), 0)
  const expense = data.total_amount != null
    ? Math.max(0, Math.round(data.total_amount) - Math.round(nonfoodSum))
    : list.filter((r) => isPantryCat(r.category) && (r.price ?? 0) > 0).reduce((s, r) => s + Math.round(r.price ?? 0), 0)
  const keepCount = list.filter((r) => r.keep && isPantryCat(r.category) && r.storage).length
  const reviewCount = list.filter((r) => r.needs_review).length

  const onConfirm = () => {
    if (list.some((r) => r.name.trim() === '')) return setFormErr('품목명이 비어 있는 줄이 있어요.')
    setFormErr(null)
    confirm.mutate(
      {
        store: data.store, purchased_at: data.purchased_at, total_amount: data.total_amount,
        items: list.map((r) => ({
          raw_text: r.raw_text, name: r.name.trim(), item_id: r.item_id, quantity: r.quantity,
          price: r.price, is_food: r.is_food, category: r.category,
          storage: isPantryCat(r.category) ? r.storage : null,
          expire_at: r.expire_at || null, keep: r.keep,
        })),
      },
      { onSuccess: (res) => setResult(res), onError: (e) => setFormErr(e instanceof Error ? e.message : '등록 실패') },
    )
  }

  return (
    <div>
      <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 10 }}>
        <span style={{ cursor: 'pointer' }} onClick={() => nav('/ocr')}>영수증 OCR</span> / 결과 확인
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>OCR 결과 확인</h1>
        <span style={{ padding: '4px 10px', fontSize: 12, fontWeight: 700, background: '#E7EFF8', color: '#1E5F96' }}>{list.length}개 인식됨</span>
      </div>
      <div style={{ background: '#FCEBDD', color: '#F26419', fontSize: 12.5, padding: '12px 16px', marginBottom: 14 }}>
        인식 결과를 확인하고 필요하면 수정하세요. <b>확인을 눌러야</b> 재고·식비에 반영됩니다.
        {reviewCount > 0 && <> · <b>{reviewCount}줄</b>은 확인이 필요해요(주황 표시).</>}
      </div>
      <div style={{ fontSize: 12, color: '#9A9A9A', marginBottom: 10 }}>{[data.store, data.purchased_at?.slice(0, 10)].filter(Boolean).join(' · ') || '영수증'}</div>

      <div style={{ overflowX: 'auto', border: '1px solid #E6E6E6' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5, minWidth: 720 }}>
          <thead>
            <tr>
              <th style={{ ...th, width: 34 }}>담기</th>
              <th style={th}>품목</th>
              <th style={{ ...th, width: 96 }}>분류</th>
              <th style={{ ...th, width: 90 }}>보관</th>
              <th style={{ ...th, width: 140 }}>소비기한</th>
              <th style={{ ...th, textAlign: 'right', width: 96 }}>가격</th>
            </tr>
          </thead>
          <tbody>
            {list.map((r, i) => {
              const pantryable = isPantryCat(r.category)
              return (
                <tr key={i} style={r.needs_review ? { background: '#FFF7F0' } : undefined}>
                  <td style={{ ...cell, textAlign: 'center' }}>
                    <input type="checkbox" checked={r.keep} disabled={!pantryable}
                      onChange={(e) => patch(i, { keep: e.target.checked })} />
                  </td>
                  <td style={cell}>
                    <input value={r.name} onChange={(e) => patch(i, { name: e.target.value })} style={inp} />
                    <div style={{ fontSize: 10.5, color: '#B8B8B8', marginTop: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {r.needs_review && <span style={{ color: '#F26419', fontWeight: 700 }}>확인 </span>}{r.raw_text}
                    </div>
                  </td>
                  <td style={cell}>
                    <select value={r.category ?? ''} onChange={(e) => onCategory(i, e.target.value)} style={inp}>
                      {r.category == null && <option value="">미분류</option>}
                      {CATS.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </td>
                  <td style={cell}>
                    {pantryable ? (
                      <select value={r.storage ?? 'FRIDGE'} onChange={(e) => patch(i, { storage: e.target.value as PantryStorage })} style={inp}>
                        {STORAGES.map((s) => <option key={s.v} value={s.v}>{s.label}</option>)}
                      </select>
                    ) : <span style={{ color: '#C4C4C4' }}>—</span>}
                  </td>
                  <td style={cell}>
                    {pantryable ? (
                      <input type="date" value={r.expire_at} onChange={(e) => patch(i, { expire_at: e.target.value })} style={inp} />
                    ) : <span style={{ color: '#C4C4C4' }}>—</span>}
                  </td>
                  <td style={{ ...cell, textAlign: 'right' }}>
                    <input type="number" value={r.price ?? ''} onChange={(e) => patch(i, { price: e.target.value === '' ? null : Number(e.target.value) })}
                      style={{ ...inp, textAlign: 'right' }} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 16, padding: '14px 16px', background: '#FCEBDD', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 12, color: '#F26419' }}>식비 (합계 − 비식품) → 캘린더 자동 기록 · 냉장고 {keepCount}개 담기</div>
          <div className="num" style={{ fontSize: 20, fontWeight: 800, color: '#F26419' }}>{won(expense)}원</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => nav('/ocr')} style={{ padding: '11px 14px', border: '1.5px solid #E6E6E6', background: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>다시 촬영</button>
          <button onClick={onConfirm} disabled={confirm.isPending}
            style={{ padding: '11px 18px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer', opacity: confirm.isPending ? 0.7 : 1 }}>
            {confirm.isPending ? '등록 중…' : '확인하고 등록'}
          </button>
        </div>
      </div>
      {formErr && <div style={{ fontSize: 12.5, color: '#F04452', fontWeight: 700, marginTop: 10 }}>{formErr}</div>}
    </div>
  )
}

function Analyzing() {
  return (
    <div style={{ textAlign: 'center', padding: '80px 20px' }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: '#F26419', marginBottom: 8 }}>영수증 분석 중…</div>
      <div style={{ fontSize: 13, color: '#9A9A9A' }}>품목·가격을 인식하고 있어요. 잠시만 기다려 주세요.</div>
    </div>
  )
}

function Notice({ title, body, onBack }: { title: string; body: string; onBack: () => void }) {
  return (
    <div style={{ textAlign: 'center', padding: '60px 20px' }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: '#17264A', marginBottom: 8 }}>{title}</div>
      <div style={{ fontSize: 13, color: '#9A9A9A', marginBottom: 18 }}>{body}</div>
      <button onClick={onBack} style={{ padding: '10px 18px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>업로드로 →</button>
    </div>
  )
}
