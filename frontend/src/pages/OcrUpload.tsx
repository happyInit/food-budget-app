import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSubmitOcr } from '../lib/queries'

// 영수증 이미지 업로드 → OCR 엔진 접수(job_id) → 결과 페이지로(폴링·HITL 확정).
export default function OcrUpload() {
  const nav = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)
  const submit = useSubmitOcr()
  const [err, setErr] = useState<string | null>(null)

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // 같은 파일 재선택 허용
    if (!file) return
    if (file.size > 10 * 1024 * 1024) return setErr('이미지가 너무 커요 (최대 10MB)')
    setErr(null)
    submit.mutate(file, {
      onSuccess: (acc) => nav(`/ocr/result?job=${acc.job_id}`),
      onError: (e2) => setErr(e2 instanceof Error ? e2.message : '업로드 실패'),
    })
  }

  const busy = submit.isPending
  return (
    <div>
      <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 10 }}>
        <span style={{ cursor: 'pointer' }} onClick={() => nav('/pantry')}>내 냉장고</span> / 영수증 OCR 등록
      </div>
      <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: '0 0 20px' }}>영수증으로 재고 등록</h1>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 16 }}>
        <div>
          <input ref={fileRef} type="file" accept="image/*" capture="environment" onChange={onPick} style={{ display: 'none' }} />
          <div
            onClick={() => !busy && fileRef.current?.click()}
            style={{
              border: '2px dashed #F26419', padding: '52px 24px', textAlign: 'center',
              background: '#FCEBDD', cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.7 : 1,
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 700, color: '#F26419' }}>
              {busy ? '업로드 중…' : '촬영 또는 이미지 업로드'}
            </div>
            <div style={{ fontSize: 12.5, color: '#9A9A9A', marginTop: 6 }}>종이 영수증 · 이커머스 결제 캡처 지원</div>
          </div>
          {err && <div style={{ fontSize: 12.5, color: '#F04452', fontWeight: 700, marginTop: 10 }}>{err}</div>}
          <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 12, lineHeight: 1.7 }}>
            · 지원 형식: JPG, PNG (최대 10MB)<br />
            · 분석 결과는 저장 전에 직접 수정할 수 있어요<br />
            · 확인을 눌러야 재고·식비에 반영돼요 (자동 확정 X)
          </div>
        </div>
        <div style={{ background: '#fff', border: '1px solid #E6E6E6', padding: 20 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>이렇게 처리돼요</h3>
          <div style={{ fontSize: 13, color: '#5E5E5E', lineHeight: 2.1 }}>
            1 이미지 업로드 → OCR 텍스트 인식<br />
            2 재료 NER → 표준 품목코드로 정규화<br />
            3 식재료·보관법 자동 분류<br />
            4 <b>사용자 확인·수정</b> 후 재고 반영 (자동 확정 X)<br />
            5 결제 금액 → 식비 캘린더 자동 기록
          </div>
        </div>
      </div>
    </div>
  )
}
