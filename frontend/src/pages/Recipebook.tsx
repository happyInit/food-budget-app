import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { img } from '../lib/data'
import {
  useBookmarks, useRemoveBookmark, useMyRecipes, useDeleteMyRecipe, useShareMyRecipe,
} from '../lib/queries'
import Modal from '../components/Modal'
import RecipeWriteForm from '../components/forms/RecipeWriteForm'
import YoutubeExtractForm from '../components/forms/YoutubeExtractForm'

// 통합 카드 — 내가 만든 레시피(mine)와 담은 레시피(book)를 한 목록으로. 태그로만 구분.
type Card =
  | { kind: 'mine'; id: number; title: string; image_url?: string | null; is_public: boolean }
  | { kind: 'book'; id: number; recipe_id: number; name: string; image_url?: string | null; cooking_time?: string | null; level_nm?: string | null }

export default function Recipebook() {
  const nav = useNavigate()
  const [modal, setModal] = useState<null | 'write' | 'youtube'>(null)
  const [share, setShare] = useState<null | { title: string; link: string }>(null)
  const [copied, setCopied] = useState(false)

  const { data: bookData, isLoading, error } = useBookmarks()
  const remove = useRemoveBookmark()
  const { data: mine } = useMyRecipes()
  const delMine = useDeleteMyRecipe()
  const shareMine = useShareMyRecipe()

  const books = bookData?.books ?? []
  const myRecipes = mine?.recipes ?? []

  // 내가 만든 것 먼저, 담은 것 다음 — 한 그리드로 통합.
  const cards: Card[] = [
    ...myRecipes.map((r): Card => ({ kind: 'mine', id: r.id, title: r.title, image_url: r.image_url, is_public: r.is_public })),
    ...books.map((b): Card => ({ kind: 'book', id: b.id, recipe_id: b.recipe_id, name: b.name, image_url: b.image_url, cooking_time: b.cooking_time, level_nm: b.level_nm })),
  ]

  const onShare = (id: number, title: string) =>
    shareMine.mutate(id, {
      onSuccess: (info) => {
        setCopied(false)
        const link = `${window.location.origin}/shared/${info.share_token}`
        setShare({ title, link })
        navigator.clipboard?.writeText(link).then(() => setCopied(true)).catch(() => {})
      },
    })

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 6 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>내 레시피북 {cards.length > 0 && <span style={{ fontSize: 15, color: '#9A9A9A' }}>{cards.length}</span>}</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setModal('write')} style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>직접 작성</button>
          <button onClick={() => setModal('youtube')} style={{ padding: '9px 14px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>YouTube 추가</button>
        </div>
      </div>
      <p style={{ fontSize: 13.5, color: '#5E5E5E', margin: '0 0 18px' }}>직접 만든 레시피와 담아둔 레시피를 한곳에서 관리해요.</p>

      {isLoading && <div style={{ color: '#9A9A9A', padding: '20px 4px' }}>불러오는 중…</div>}
      {error && (
        <div style={{ padding: '16px 4px' }}>
          <div style={{ color: '#F04452', fontWeight: 700, marginBottom: 6 }}>레시피북을 불러오지 못했어요</div>
          <div style={{ color: '#9A9A9A', fontSize: 13 }}>{error.message}</div>
        </div>
      )}

      {!isLoading && !error && cards.length === 0 && (
        <div style={{ textAlign: 'center', padding: '40px 20px', background: '#FAFAFA', border: '1px solid #EFEFEF' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#17264A', marginBottom: 6 }}>아직 레시피가 없어요</div>
          <div style={{ fontSize: 13, color: '#9A9A9A', marginBottom: 16 }}><b style={{ color: '#F26419' }}>직접 작성</b>으로 등록하거나, 레시피 상세에서 <b style={{ color: '#F26419' }}>레시피북 저장</b>으로 담아보세요.</div>
          <button onClick={() => nav('/recipes')} style={{ padding: '10px 18px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>레시피 탐색 →</button>
        </div>
      )}

      {cards.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(190px,1fr))', gap: 14 }}>
          {cards.map((c) => (
            <div key={`${c.kind}-${c.id}`} style={{ background: '#fff', border: '1px solid #E6E6E6', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <div
                onClick={c.kind === 'book' ? () => nav('/recipes/' + c.recipe_id) : undefined}
                className={c.kind === 'book' ? 'zoom-wrap' : undefined}
                style={{ height: 108, background: '#F0F0F0', cursor: c.kind === 'book' ? 'pointer' : 'default', position: 'relative' }}
              >
                <div className={c.kind === 'book' ? 'zoom' : undefined} style={{ width: '100%', height: '100%', background: `center/cover no-repeat url("${c.image_url || img(c.id, 300)}")` }} />
              </div>
              <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
                  {c.kind === 'mine' ? (
                    <span style={{ fontSize: 10.5, fontWeight: 700, color: '#F26419', background: '#FCEBDD', padding: '2px 6px' }}>내가 만든</span>
                  ) : (
                    <span style={{ fontSize: 10.5, fontWeight: 700, color: '#1E5F96', background: '#E7EFF8', padding: '2px 6px' }}>담은</span>
                  )}
                  {c.kind === 'mine' && c.is_public && <span style={{ fontSize: 10.5, fontWeight: 700, color: '#1B7A46', background: '#E7F5EC', padding: '2px 6px' }}>공개중</span>}
                </div>
                <div style={{ fontSize: 14, fontWeight: 700, lineHeight: 1.3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {c.kind === 'mine' ? c.title : c.name}
                </div>
                {c.kind === 'book' && (
                  <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: -3 }}>
                    {[c.cooking_time, c.level_nm].filter(Boolean).join(' · ') || '만개의레시피'}
                  </div>
                )}
                <div style={{ display: 'flex', gap: 6, marginTop: 'auto' }}>
                  {c.kind === 'mine' ? (
                    <>
                      <button onClick={() => onShare(c.id, c.title)} disabled={shareMine.isPending}
                        style={{ flex: 1, padding: '7px 0', border: '1.5px solid #F26419', background: '#fff', color: '#F26419', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>
                        {c.is_public ? '공유 링크' : '공유'}
                      </button>
                      <button onClick={() => { if (confirm(`"${c.title}" 삭제할까요?`)) delMine.mutate(c.id) }} disabled={delMine.isPending}
                        aria-label="삭제"
                        style={{ padding: '7px 12px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#9A9A9A', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>
                        삭제
                      </button>
                    </>
                  ) : (
                    <>
                      <button onClick={() => nav('/recipes/' + c.recipe_id)}
                        style={{ flex: 1, padding: '7px 0', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>
                        보기
                      </button>
                      <button onClick={() => remove.mutate(c.id)} disabled={remove.isPending}
                        aria-label="레시피북에서 빼기" title="레시피북에서 빼기"
                        style={{ padding: '7px 12px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#9A9A9A', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>
                        빼기
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal open={modal === 'write'} onClose={() => setModal(null)} title="레시피 직접 작성">
        <RecipeWriteForm onDone={() => setModal(null)} />
      </Modal>
      <Modal open={modal === 'youtube'} onClose={() => setModal(null)} title="YouTube 레시피 추출">
        <YoutubeExtractForm onDone={() => setModal(null)} />
      </Modal>

      {/* 공유 링크 모달 */}
      <Modal open={!!share} onClose={() => setShare(null)} title="레시피 공유">
        {share && (
          <div>
            <div style={{ fontSize: 13, color: '#5E5E5E', marginBottom: 10 }}><b style={{ color: '#17264A' }}>{share.title}</b> 공개 링크예요. 링크를 아는 사람이면 로그인 없이 볼 수 있어요.</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input readOnly value={share.link} onFocus={(e) => e.currentTarget.select()}
                style={{ flex: 1, padding: '10px 12px', border: '1.5px solid #E6E6E6', fontSize: 12.5, outline: 'none', minWidth: 0 }} />
              <button onClick={() => { navigator.clipboard?.writeText(share.link).then(() => setCopied(true)) }}
                style={{ padding: '0 16px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' }}>
                {copied ? '복사됨 ✓' : '복사'}
              </button>
            </div>
            <button onClick={() => window.open(share.link, '_blank')} style={{ width: '100%', marginTop: 10, padding: 10, border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>새 탭에서 열어보기</button>
          </div>
        )}
      </Modal>
    </div>
  )
}
