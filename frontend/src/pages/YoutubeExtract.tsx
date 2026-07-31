import { useState } from 'react'
import { useSubmitExtract, useExtractJob } from '../lib/queries'
import { won } from '../lib/api'

const card: React.CSSProperties = { background: '#fff', border: '1px solid #E6E6E6', padding: 20 }

export default function YoutubeExtract() {
  const [url, setUrl] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const submit = useSubmitExtract()
  const job = useExtractJob(jobId)
  const r = job.data

  const start = () => {
    if (!url.trim()) return
    submit.mutate(url.trim(), { onSuccess: (a) => setJobId(a.job_id) })
  }

  const pending = submit.isPending || r?.status === 'PENDING'
  const err =
    (submit.error as Error | null)?.message ??
    (r?.status === 'FAILED' ? r.reason ?? '추출에 실패했어요.' : null)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 18 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>YouTube 레시피 추출</h1>
        <span style={{ padding: '3px 9px', fontSize: 11, fontWeight: 700, background: '#FCEBDD', color: '#F26419' }}>P1</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 16 }}>
        <div>
          <div style={{ border: '2px dashed #E6E6E6', padding: '44px 24px', textAlign: 'center', marginBottom: 14 }}>
            <div style={{ fontSize: 15, fontWeight: 700 }}>YouTube URL을 붙여넣으세요</div>
            <div style={{ fontSize: 12.5, color: '#9A9A9A', marginTop: 6 }}>영상 멀티모달 분석 → AI가 재료·조리단계를 추출합니다</div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') start() }}
              placeholder="https://youtube.com/watch?v=…"
              style={{ flex: 1, padding: '11px 14px', border: '1.5px solid #E6E6E6', fontSize: 14, outline: 'none', minWidth: 0 }}
            />
            <button
              onClick={start}
              disabled={pending || !url.trim()}
              style={{ padding: '0 18px', border: 'none', background: pending ? '#C9C9C9' : '#F26419', color: '#fff', fontSize: 14, fontWeight: 700, cursor: pending ? 'default' : 'pointer', whiteSpace: 'nowrap' }}
            >{pending ? '분석 중…' : '추출'}</button>
          </div>
          {r?.from_cache && <div style={{ fontSize: 12, color: '#1BAF7A', marginTop: 8 }}>이미 분석된 영상이라 즉시 불러왔어요.</div>}
          {err && <div style={{ background: '#FDECEC', color: '#E34948', fontSize: 12.5, padding: '11px 14px', marginTop: 12 }}>{err}</div>}
          <div style={{ background: '#FCEBDD', color: '#F26419', fontSize: 12, padding: '11px 14px', marginTop: 12 }}>영상 검사 후 요리 영상이 아니거나 추출 실패 시 안내됩니다. (비용 상한 관리)</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={card}>
            <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 10px' }}>추출 파이프라인</h3>
            <div style={{ fontSize: 13, color: '#5E5E5E', lineHeight: 2.1 }}>
              1. 영상 사전필터 · 캐시 확인<br />
              2. Gemini 멀티모달 → 재료·단계 추출<br />
              3. CRF NER → 재료 정규화<br />
              4. 마켓컬리 상품 매핑 · 가격 산출<br />
              5. 결과 확인·수정 → 레시피북 저장
            </div>
          </div>
        </div>
      </div>

      {r?.status === 'DONE' && (
        <div style={{ marginTop: 18, display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 16 }}>
          <div style={card}>
            <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 4px' }}>{r.title ?? '제목 없음'}</h3>
            {/* 인분 미상은 추정하지 않는다 — 틀린 인분은 재료비를 그대로 왜곡한다. */}
            <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 12 }}>
              {r.servings_known && r.servings ? r.servings : '인분 미상 · 직접 입력'}
            </div>
            <h4 style={{ fontSize: 13.5, fontWeight: 700, margin: '0 0 8px' }}>재료 {r.ingredients.length}개</h4>
            {r.ingredients.map((g, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '5px 0', borderTop: i ? '1px solid #EFEFEF' : 'none' }}>
                <span>{g.name}</span>
                <span style={{ color: '#9A9A9A' }}>{g.quantity ?? '-'}</span>
              </div>
            ))}
          </div>

          <div style={card}>
            <h4 style={{ fontSize: 13.5, fontWeight: 700, margin: '0 0 8px' }}>조리 순서</h4>
            <ol style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: '#5E5E5E', lineHeight: 1.9 }}>
              {r.steps.map((s) => <li key={s.order}>{s.text}</li>)}
            </ol>
          </div>

          {r.cost && (
            <div style={card}>
              <h4 style={{ fontSize: 13.5, fontWeight: 700, margin: '0 0 8px' }}>재료비</h4>
              <div style={{ fontSize: 22, fontWeight: 800, color: '#F26419' }}>
                {r.cost.total_krw == null ? '산출 불가' : `${won(r.cost.total_krw)}원~`}
              </div>
              {/* 재료비는 모르는 값을 지어내지 않아 **항상 과소추정**이다.
                  총액만 보이면 유저가 실제보다 싸다고 오해하므로 산출 범위를 함께 노출한다. */}
              <div style={{ fontSize: 12, color: '#9A9A9A', marginTop: 4 }}>
                재료 {r.cost.total_count}개 중 {r.cost.priced_count}개 기준
                {r.cost.excluded_count > 0 && ` · 상비 재료 ${r.cost.excluded_count}개 제외`}
              </div>
              {r.cost.per_serving_krw != null && (
                <div style={{ fontSize: 13, color: '#5E5E5E', marginTop: 6 }}>1인분 약 {won(r.cost.per_serving_krw)}원</div>
              )}
              <div style={{ marginTop: 10 }}>
                {r.cost.lines.map((ln, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, padding: '4px 0', borderTop: '1px solid #EFEFEF' }}>
                    <span style={{ color: ln.krw == null ? '#9A9A9A' : '#0B0B0B' }}>{ln.name}</span>
                    <span style={{ color: ln.krw == null ? '#9A9A9A' : '#5E5E5E' }}>
                      {ln.krw == null ? (ln.reason ?? '-') : `${won(ln.krw)}원`}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
