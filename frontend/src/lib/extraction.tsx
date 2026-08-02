import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { useSubmitExtract, useExtractJob, useCreateMyRecipe } from './queries'
import type { ExtractStatus } from './api'

type Phase = 'analyzing' | 'done' | 'saving' | 'error'
type Ctx = {
  active: boolean
  phase: Phase
  result: ExtractStatus | null
  error: string | null
  start: (url: string) => void
  confirm: () => void // 유저 확인 → 레시피북 저장
  dismiss: () => void
}

const ExtractionContext = createContext<Ctx | null>(null)
export const useExtraction = () => useContext(ExtractionContext)

// 유튜브 URL → 대표이미지(썸네일). videoId 11자 추출(watch?v=·youtu.be/·shorts/·embed/·live/).
// hqdefault 는 모든 영상에 항상 존재(안전). 못 뽑으면 null → 저장측이 기본 썸네일 폴백.
function youtubeThumb(url: string): string | null {
  const m = url.match(/(?:youtu\.be\/|youtube\.com\/(?:watch\?(?:[^&]*&)*v=|shorts\/|embed\/|live\/))([\w-]{11})/)
  return m ? `https://img.youtube.com/vi/${m[1]}/hqdefault.jpg` : null
}

// YouTube 추출을 백그라운드 잡으로 관리 — 모달이 닫혀도·페이지를 옮겨도 진행이 이어진다.
// 완료되면 레시피북 카드가 '완료' 상태가 되고, 유저가 '확인 후 담기'로 확정해야 저장한다(1회).
export function ExtractionProvider({ children }: { children: ReactNode }) {
  const [url, setUrl] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const submit = useSubmitExtract()
  const create = useCreateMyRecipe()
  const job = useExtractJob(jobId)
  const r = job.data ?? null

  const start = (raw: string) => {
    const v = raw.trim()
    if (!v) return
    setError(null)
    setJobId(null)
    setUrl(v)
    submit.mutate(v, {
      onSuccess: (a) => setJobId(a.job_id),
      onError: (e) => setError((e as Error).message || '요청에 실패했어요.'),
    })
  }
  const dismiss = () => {
    setUrl(null)
    setJobId(null)
    setError(null)
  }
  const confirm = () => {
    if (!r || r.status !== 'DONE' || !url || create.isPending) return
    create.mutate(
      {
        title: r.title ?? 'YouTube 레시피',
        ingredients: r.ingredients.map((g) => ({ name: g.name, quantity: g.quantity, item_id: g.item_id })),
        steps: r.steps.map((s) => s.text),
        source_url: url,
        source_creator: r.source_creator, // 유튜브 채널명(출처)
        image_url: youtubeThumb(url), // 유튜브 썸네일을 대표이미지로
        serving: r.servings_known ? r.servings : null,
      },
      {
        onSuccess: () => { setUrl(null); setJobId(null) },
        onError: () => setError('레시피북 저장에 실패했어요.'),
      },
    )
  }

  // FAILED 만 오류 처리. DONE 은 phase='done' 으로 노출 → 유저 확인 대기(자동저장 안 함).
  useEffect(() => {
    if (r?.status === 'FAILED') setError(r.reason ?? '요리 영상이 아니거나 분석에 실패했어요.')
  }, [r?.status, r?.reason])

  const active = url != null
  const phase: Phase = error ? 'error' : create.isPending ? 'saving' : r?.status === 'DONE' ? 'done' : 'analyzing'

  return (
    <ExtractionContext.Provider value={{ active, phase, result: r, error, start, confirm, dismiss }}>
      {children}
    </ExtractionContext.Provider>
  )
}
