import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { img } from '../lib/data'
import { useBookmarks, useRemoveBookmark } from '../lib/queries'
import Modal from '../components/Modal'
import RecipeWriteForm from '../components/forms/RecipeWriteForm'
import YoutubeExtractForm from '../components/forms/YoutubeExtractForm'

export default function Recipebook() {
  const nav = useNavigate()
  const [modal, setModal] = useState<null | 'write' | 'youtube'>(null)
  const { data, isLoading, error } = useBookmarks()
  const remove = useRemoveBookmark()

  const books = data?.books ?? []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 16 }}>
        <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: 0 }}>내 레시피북</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setModal('write')} style={{ padding: '9px 14px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>직접 작성</button>
          <button onClick={() => setModal('youtube')} style={{ padding: '9px 14px', border: 'none', background: '#F26419', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>YouTube 추가</button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 18 }}>
        <span style={{ padding: '7px 14px', fontSize: 13, fontWeight: 700, border: '1.5px solid #F26419', background: '#F26419', color: '#fff' }}>
          담은 레시피 {books.length}
        </span>
      </div>

      {isLoading && <div style={{ color: '#9A9A9A', padding: '40px 4px' }}>불러오는 중…</div>}

      {error && (
        <div style={{ padding: '30px 4px' }}>
          <div style={{ color: '#F04452', fontWeight: 700, marginBottom: 6 }}>레시피북을 불러오지 못했어요</div>
          <div style={{ color: '#9A9A9A', fontSize: 13 }}>{error.message}</div>
        </div>
      )}

      {!isLoading && !error && books.length === 0 && (
        <div style={{ textAlign: 'center', padding: '56px 20px', background: '#FAFAFA', border: '1px solid #EFEFEF' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#17264A', marginBottom: 6 }}>아직 담은 레시피가 없어요</div>
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
              {/* 삭제(북마크 해제) */}
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
    </div>
  )
}
