import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { img } from '../lib/data'
import {
  useBookmarks, useRemoveBookmark, useMyRecipes, useDeleteMyRecipe, useShareMyRecipe,
} from '../lib/queries'
import Modal from '../components/Modal'
import RecipeWriteForm from '../components/forms/RecipeWriteForm'
import YoutubeExtractForm from '../components/forms/YoutubeExtractForm'

export default function Recipebook() {
  const nav = useNavigate()
  const [modal, setModal] = useState<null | 'write' | 'youtube'>(null)
  const [share, setShare] = useState<null | { title: string; link: string }>(null)
  const [copied, setCopied] = useState(false)

  const { data, isLoading, error } = useBookmarks()
  const remove = useRemoveBookmark()
  const { data: mine } = useMyRecipes()
  const delMine = useDeleteMyRecipe()
  const shareMine = useShareMyRecipe()

  const books = data?.books ?? []
  const myRecipes = mine?.recipes ?? []

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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 16 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>내 레시피북</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setModal('write')} style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>직접 작성</button>
          <button onClick={() => setModal('youtube')} style={{ padding: '9px 14px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>YouTube 추가</button>
        </div>
      </div>

      {/* ── 내가 만든 레시피 (수동 등록 + 공유) ── */}
      <h2 style={{ fontSize: 15, fontWeight: 800, color: '#17264A', margin: '4px 0 12px' }}>내가 만든 레시피 {myRecipes.length > 0 && <span style={{ color: '#9A9A9A' }}>{myRecipes.length}</span>}</h2>
      {myRecipes.length === 0 ? (
        <div style={{ padding: '20px', background: '#FAFAFA', border: '1px solid #EFEFEF', fontSize: 13, color: '#9A9A9A', marginBottom: 26 }}>
          <b style={{ color: '#17264A' }}>직접 작성</b>으로 나만의 레시피를 등록하고 링크로 공유해보세요.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(220px,1fr))', gap: 12, marginBottom: 26 }}>
          {myRecipes.map((r) => (
            <div key={r.id} style={{ background: '#fff', border: '1px solid #E6E6E6', overflow: 'hidden' }}>
              <div style={{ height: 96, background: `#F0F0F0 center/cover no-repeat url("${r.image_url || img(r.id, 300)}")` }} />
              <div style={{ padding: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{ fontSize: 14, fontWeight: 700, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.title}</div>
                  {r.is_public && <span style={{ fontSize: 10.5, fontWeight: 700, color: '#1B7A46', background: '#E7F5EC', padding: '2px 6px' }}>공개중</span>}
                </div>
                <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                  <button onClick={() => onShare(r.id, r.title)} disabled={shareMine.isPending}
                    style={{ flex: 1, padding: '7px 0', border: '1.5px solid #F26419', background: '#fff', color: '#F26419', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>
                    {r.is_public ? '공유 링크' : '공유'}
                  </button>
                  <button onClick={() => { if (confirm(`"${r.title}" 삭제할까요?`)) delMine.mutate(r.id) }} disabled={delMine.isPending}
                    aria-label="삭제"
                    style={{ padding: '7px 12px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#9A9A9A', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>
                    삭제
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── 담은 레시피 (북마크) ── */}
      <h2 style={{ fontSize: 15, fontWeight: 800, color: '#17264A', margin: '4px 0 12px' }}>담은 레시피 {books.length > 0 && <span style={{ color: '#9A9A9A' }}>{books.length}</span>}</h2>

      {isLoading && <div style={{ color: '#9A9A9A', padding: '20px 4px' }}>불러오는 중…</div>}

      {error && (
        <div style={{ padding: '16px 4px' }}>
          <div style={{ color: '#F04452', fontWeight: 700, marginBottom: 6 }}>레시피북을 불러오지 못했어요</div>
          <div style={{ color: '#9A9A9A', fontSize: 13 }}>{error.message}</div>
        </div>
      )}

      {!isLoading && !error && books.length === 0 && (
        <div style={{ textAlign: 'center', padding: '40px 20px', background: '#FAFAFA', border: '1px solid #EFEFEF' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#17264A', marginBottom: 6 }}>아직 담은 레시피가 없어요</div>
          <div style={{ fontSize: 13, color: '#9A9A9A', marginBottom: 16 }}>레시피 상세에서 <b style={{ color: '#F26419' }}>레시피북 저장</b>을 눌러 담아보세요.</div>
          <button onClick={() => nav('/recipes')} style={{ padding: '10px 18px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>레시피 탐색 →</button>
        </div>
      )}

      {books.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 12 }}>
          {books.map((b) => (
            <div key={b.id} style={{ position: 'relative' }}>
              <div onClick={() => nav('/recipes/' + b.recipe_id)} className="zoom-wrap" style={{ aspectRatio: '1', cursor: 'pointer', background: '#F0F0F0', position: 'relative' }}>
                <div className="zoom" style={{ width: '100%', height: '100%', background: `center/cover no-repeat url("${b.image_url || img(b.recipe_id, 300)}")` }} />
                <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: '18px 10px 9px', background: 'linear-gradient(transparent, rgba(0,0,0,.62))', color: '#fff' }}>
                  <div style={{ fontSize: 13, fontWeight: 700, lineHeight: 1.25 }}>{b.name}</div>
                  <div style={{ fontSize: 10.5, opacity: 0.85, marginTop: 2 }}>
                    {[b.cooking_time, b.level_nm].filter(Boolean).join(' · ') || ' '}
                  </div>
                </div>
              </div>
              <button
                onClick={() => remove.mutate(b.id)}
                disabled={remove.isPending}
                aria-label="레시피북에서 빼기"
                title="레시피북에서 빼기"
                style={{ position: 'absolute', top: 6, right: 6, width: 26, height: 26, borderRadius: '50%', border: 'none', background: 'rgba(23,38,74,.72)', color: '#fff', fontSize: 13, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}
              >
                ✕
              </button>
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
