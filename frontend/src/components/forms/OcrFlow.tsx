import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSubmitOcr, useOcrJob, useConfirmReceipt } from '../../lib/queries'
import type { OcrItem, PantryStorage, ReceiptConfirmResult } from '../../lib/api'
import { won } from '../../lib/api'
import { primaryBtn, ghostBtn } from './formStyles'

const th: React.CSSProperties = { textAlign: 'left', padding: '8px 8px', borderBottom: '2px solid #E6E6E6', fontSize: 11.5, color: '#5E5E5E', fontWeight: 600, whiteSpace: 'nowrap' }
const cell: React.CSSProperties = { padding: '8px 8px', borderBottom: '1px solid #EFEFEF', verticalAlign: 'middle' }
const inp: React.CSSProperties = { padding: '6px 8px', border: '1.5px solid #E6E6E6', fontSize: 12.5, outline: 'none', width: '100%', boxSizing: 'border-box' }

// 🔴 **서버 상한과 같은 값이어야 한다** — `services/ocr/app/config.py` 의 `max_image_bytes`.
//    갈리면 «업로드는 됐는데 서버가 거절» 이 되고, 유저는 기다린 뒤에야 안다.
const MAX_UPLOAD_BYTES = 8 * 1024 * 1024

const CATS = ['식재료', '가공식품', '비식품', '조정'] as const
const STORAGES: { v: PantryStorage; label: string }[] = [
  { v: 'ROOM', label: '실온' }, { v: 'FRIDGE', label: '냉장' }, { v: 'FREEZER', label: '냉동' },
]
const isPantryCat = (c: string | null) => c !== '비식품' && c !== '조정'

// OCR 엔진 미배포/게이트웨이 오류(502·503·504)는 원시 메시지 대신 안내로.
function friendlyOcrError(e: unknown): string {
  const m = e instanceof Error ? e.message : '업로드 실패'
  if (/\b50[234]\b|bad gateway|gateway time|unavailable|failed to fetch|networkerror/i.test(m))
    return '영수증 인식 서버에 연결할 수 없어요. 잠시 후 다시 시도하거나 관리자에게 문의해 주세요.'
  return m
}

type Row = {
  raw_text: string | null
  name: string
  item_id: number | null
  quantity: string | null
  price: number | null
  is_food: boolean
  category: string | null
  storage: PantryStorage | null
  expire_at: string
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

// 영수증 OCR — 모달 안에서 업로드 → 폴링 → HITL 편집 → 확정까지. (Fridge·Cart·Home 진입점 공용)
export default function OcrFlow({ onClose }: { onClose: () => void }) {
  const nav = useNavigate()
  const submit = useSubmitOcr()
  const confirm = useConfirmReceipt()
  const fileRef = useRef<HTMLInputElement>(null)

  const [jobId, setJobId] = useState<string | null>(null)
  const { data, error } = useOcrJob(jobId)
  const [rows, setRows] = useState<Row[] | null>(null)
  const seeded = useRef(false)
  const [result, setResult] = useState<(ReceiptConfirmResult & { expenseRecorded: boolean }) | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [preview, setPreview] = useState<string | null>(null) // 업로드한 영수증 원본(objectURL) — 인식결과 대조용
  const [zoom, setZoom] = useState(false)

  // 언마운트 시 objectURL 해제(메모리 누수 방지)
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  useEffect(() => {
    if (data?.status === 'DONE' && !seeded.current) {
      seeded.current = true
      setRows(data.items.map(toRow))
    }
  }, [data])

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    // 🔴 서버 상한과 맞춘다 — `services/ocr/app/config.py` 의 `max_image_bytes = 8MB`.
    //    프론트가 10MB 까지 통과시키고 있어서, 8~10MB 사진은 **다 업로드한 뒤** 서버에서
    //    거절됐다. 모바일 원본 사진이 정확히 그 구간에 잘 걸린다 — 기다린 만큼 헛수고다.
    // 🔵 여기서 막으면 고르는 즉시 안다. `shrinkReceipt` 이 어차피 1600px 로 줄이므로
    //    실제로 이 한도에 걸리는 경우는 드물지만, 그때의 문구가 사실이어야 한다.
    if (file.size > MAX_UPLOAD_BYTES)
      return setErr(`이미지가 너무 커요 (최대 ${MAX_UPLOAD_BYTES / 1024 / 1024}MB)`)
    setErr(null)
    if (preview) URL.revokeObjectURL(preview)
    setPreview(URL.createObjectURL(file)) // 원본 미리보기 확보
    submit.mutate(file, {
      onSuccess: (acc) => setJobId(acc.job_id),
      onError: (e2) => setErr(friendlyOcrError(e2)),
    })
  }

  const patch = (i: number, p: Partial<Row>) =>
    setRows((rs) => (rs ? rs.map((r, idx) => (idx === i ? { ...r, ...p } : r)) : rs))
  const onCategory = (i: number, c: string) =>
    patch(i, isPantryCat(c)
      ? { category: c, keep: true, storage: rows?.[i].storage ?? 'FRIDGE' }
      : { category: c, keep: false })

  // 영수증 원본 미리보기(썸네일) + 확대 오버레이 — 인식 결과와 눈으로 대조.
  const receiptThumb = preview && (
    <button type="button" onClick={() => setZoom(true)} title="원본 확대"
      style={{ display: 'block', width: '100%', marginBottom: 12, border: '1px solid #E6E6E6', background: '#F7F4EF', padding: 6, cursor: 'zoom-in' }}>
      <img src={preview} alt="영수증 원본" style={{ width: '100%', maxHeight: 200, objectFit: 'contain', display: 'block' }} />
      <div style={{ fontSize: 11, color: '#9A9A9A', marginTop: 6, textAlign: 'center' }}>영수증 원본 · 눌러서 확대</div>
    </button>
  )
  const zoomOverlay = zoom && preview && (
    <div onClick={() => setZoom(false)} style={{ position: 'fixed', inset: 0, zIndex: 60, background: 'rgba(20,15,10,.82)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20, cursor: 'zoom-out' }}>
      <img src={preview} alt="영수증 원본" style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
    </div>
  )

  // ── 완료 요약 ──
  if (result)
    return (
      <div>
        <div style={{ background: '#E7F5EC', border: '1px solid #BCE3C9', padding: 18, marginBottom: 16 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#1B7A46', marginBottom: 8 }}>냉장고에 {result.added_count}개 재료를 담았어요</div>
          <div style={{ fontSize: 13, color: '#2E7D4F' }}>
            식비 <b>{won(result.expense_amount)}원</b>
            {result.expenseRecorded ? ' 을(를) 식비 캘린더에 기록했어요.' : ' 계산은 됐지만 캘린더 기록에 실패했어요. 식비에서 직접 추가해 주세요.'}
          </div>
          {result.needs_expense_review && (
            <div style={{ fontSize: 12, color: '#B26A00', marginTop: 8 }}>⚠ 담은 재료 중 가격이 인식되지 않은 항목이 있어요. 식비가 실제보다 적게 잡혔을 수 있어요.</div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={() => { onClose(); nav('/pantry') }} style={{ ...ghostBtn, padding: '10px 16px' }}>냉장고 보기</button>
          <button onClick={onClose} style={{ ...primaryBtn, padding: '10px 18px' }}>완료</button>
        </div>
      </div>
    )

  // ── 업로드 전 ──
  if (!jobId)
    return (
      <div>
        {/* 🔴 `capture="environment"` 를 뺐다 — 그게 있으면 **모바일이 카메라만 연다.**
            갤러리에 이미 있는 영수증 사진(또는 이커머스 결제 캡처)을 못 고른다.
            화면 문구는 «촬영 또는 이미지 업로드» 이고 안내에도 «이커머스 결제 캡처 지원» 이라
            적혀 있는데, **코드가 촬영만 허용하고 있었다** — 문구와 동작이 어긋나 있었다.
            🔵 빼면 OS 가 «카메라 / 사진 보관함» 선택지를 준다. 촬영 경로는 그대로 산다.
            ⚠️ 데스크톱은 원래 capture 를 무시하므로 이 변경의 영향이 없다. */}
        <input ref={fileRef} type="file" accept="image/*" onChange={onPick} style={{ display: 'none' }} />
        <div
          onClick={() => !submit.isPending && fileRef.current?.click()}
          style={{ border: '2px dashed #F26419', padding: '52px 24px', textAlign: 'center', background: '#FCEBDD', cursor: submit.isPending ? 'default' : 'pointer', opacity: submit.isPending ? 0.7 : 1 }}
        >
          <div style={{ fontSize: 15, fontWeight: 700, color: '#F26419' }}>{submit.isPending ? '업로드 중…' : '촬영하거나 갤러리에서 고르기'}</div>
          <div style={{ fontSize: 12.5, color: '#9A9A9A', marginTop: 6 }}>종이 영수증 · 이커머스 결제 캡처 지원</div>
        </div>
        {err && <div style={{ fontSize: 12.5, color: '#F04452', fontWeight: 700, marginTop: 10 }}>{err}</div>}
        <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 12, lineHeight: 1.7 }}>
          · 지원 형식: JPG, PNG (최대 8MB) · 갤러리 사진도 됩니다<br />
          · 분석 결과는 저장 전에 직접 수정할 수 있어요<br />
          · 확인을 눌러야 재고·식비에 반영돼요 (자동 확정 X)
        </div>
      </div>
    )

  // ── 분석 중 / 실패 ──
  if (error || data?.status === 'FAILED')
    return (
      <div style={{ textAlign: 'center', padding: '40px 10px' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#17264A', marginBottom: 8 }}>인식에 실패했어요</div>
        <div style={{ fontSize: 13, color: '#9A9A9A', marginBottom: 18 }}>{data?.reason ?? (error instanceof Error ? error.message : '다시 시도해 주세요.')}</div>
        <button onClick={() => { setJobId(null); seeded.current = false }} style={{ ...primaryBtn, padding: '10px 18px' }}>다시 업로드</button>
      </div>
    )
  if (!data || data.status === 'PENDING' || !rows)
    return (
      <div>
        {receiptThumb}
        <div style={{ textAlign: 'center', padding: '36px 10px 16px' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#F26419', marginBottom: 8 }}>영수증 분석 중…</div>
          <div style={{ fontSize: 13, color: '#9A9A9A' }}>품목·가격을 인식하고 있어요. 잠시만 기다려 주세요.</div>
        </div>
        {zoomOverlay}
      </div>
    )

  // ── DONE: HITL 편집표 ──
  const list = rows
  // 식비 미리보기 = 냉장고에 담을(keep·보관지정) 식품의 가격 합 — 백엔드 확정 로직과 동일(선택분만 차감)
  const expense = list
    .filter((r) => r.keep && isPantryCat(r.category) && r.storage != null && (r.price ?? 0) > 0)
    .reduce((s, r) => s + Math.round(r.price ?? 0), 0)
  const keepCount = list.filter((r) => r.keep && isPantryCat(r.category) && r.storage).length
  const reviewCount = list.filter((r) => r.needs_review).length

  const onConfirm = () => {
    if (list.some((r) => r.name.trim() === '')) return setErr('품목명이 비어 있는 줄이 있어요.')
    setErr(null)
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
      { onSuccess: (res) => setResult(res), onError: (e) => setErr(e instanceof Error ? e.message : '등록 실패') },
    )
  }

  return (
    <div>
      <div style={{ background: '#FCEBDD', color: '#F26419', fontSize: 12.5, padding: '10px 14px', marginBottom: 12 }}>
        인식 결과를 확인하고 필요하면 수정하세요. <b>확인을 눌러야</b> 재고·식비에 반영됩니다.
        {reviewCount > 0 && <> · <b>{reviewCount}줄</b> 확인 필요(주황).</>}
      </div>
      <div style={{ fontSize: 12, color: '#9A9A9A', marginBottom: 8 }}>{[data.store, data.purchased_at?.slice(0, 10)].filter(Boolean).join(' · ') || '영수증'} · {list.length}개 인식</div>

      {receiptThumb}

      <div style={{ overflowX: 'auto', border: '1px solid #E6E6E6' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5, minWidth: 660 }}>
          <thead>
            <tr>
              <th style={{ ...th, width: 30 }}>담기</th>
              <th style={th}>품목</th>
              <th style={{ ...th, width: 88 }}>분류</th>
              <th style={{ ...th, width: 78 }}>보관</th>
              <th style={{ ...th, width: 132 }}>소비기한</th>
              <th style={{ ...th, textAlign: 'right', width: 84 }}>가격</th>
            </tr>
          </thead>
          <tbody>
            {list.map((r, i) => {
              const pantryable = isPantryCat(r.category)
              return (
                <tr key={i} style={r.needs_review ? { background: '#FFF7F0' } : undefined}>
                  <td style={{ ...cell, textAlign: 'center' }}>
                    <input type="checkbox" checked={r.keep} disabled={!pantryable} onChange={(e) => patch(i, { keep: e.target.checked })} />
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
                    <input type="number" value={r.price ?? ''} onChange={(e) => patch(i, { price: e.target.value === '' ? null : Number(e.target.value) })} style={{ ...inp, textAlign: 'right' }} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 14, padding: '12px 14px', background: '#FCEBDD', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 11.5, color: '#F26419' }}>식비(합계−비식품) → 캘린더 · 냉장고 {keepCount}개 담기</div>
          <div className="num" style={{ fontSize: 19, fontWeight: 800, color: '#F26419' }}>{won(expense)}원</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => { setJobId(null); seeded.current = false; setRows(null) }} style={{ ...ghostBtn, padding: '10px 14px' }}>다시 촬영</button>
          <button onClick={onConfirm} disabled={confirm.isPending} style={{ ...primaryBtn, padding: '10px 16px', opacity: confirm.isPending ? 0.7 : 1 }}>
            {confirm.isPending ? '등록 중…' : '확인하고 등록'}
          </button>
        </div>
      </div>
      {err && <div style={{ fontSize: 12.5, color: '#F04452', fontWeight: 700, marginTop: 10 }}>{err}</div>}
      {zoomOverlay}
    </div>
  )
}
