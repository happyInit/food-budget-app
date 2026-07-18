import { useState } from 'react'
import { inp, lab, primaryBtn, ghostBtn } from './formStyles'
import { useCreateMyRecipe } from '../../lib/queries'
import { fileToResizedDataUrl } from '../../lib/image'
import type { UserRecipeIngredient } from '../../lib/api'

// 만개 레시피 칩과 동일한 어휘(레시피 검색 필터와 일치). 빈 값 = 미입력(상세에서 해당 칩 생략).
const TIME_OPTS = ['10분 이내', '15분 이내', '20분 이내', '30분 이내', '60분 이내']
const SERVING_OPTS = ['1인분', '2인분', '3인분', '4인분', '5인분 이상']
const LEVEL_OPTS = ['아무나', '초급', '중급']

// "김치 100g" → {name:"김치", quantity:"100g"} (마지막 공백 기준). 공백 없으면 quantity 없음.
function parseIngredient(line: string): UserRecipeIngredient {
  const t = line.trim()
  const i = t.lastIndexOf(' ')
  if (i <= 0) return { name: t }
  return { name: t.slice(0, i).trim(), quantity: t.slice(i + 1).trim() }
}

// 레시피 직접 작성 (모달 콘텐츠) → user_recipe(수동) 저장. 저장 후 목록 자동 갱신 + onDone.
export default function RecipeWriteForm({ onDone }: { onDone: () => void }) {
  const create = useCreateMyRecipe()
  const [title, setTitle] = useState('')
  const [cookingTime, setCookingTime] = useState('')  // 만개와 동일한 메타(칩) — 선택
  const [serving, setServing] = useState('')
  const [level, setLevel] = useState('')
  const [ingText, setIngText] = useState('')
  const [stepText, setStepText] = useState('')
  const [image, setImage] = useState<string | null>(null) // 리사이즈된 JPEG data URI → image_url로 저장
  const [imgBusy, setImgBusy] = useState(false)
  const [imgErr, setImgErr] = useState('')

  const onPickImage = async (file?: File) => {
    if (!file) return
    setImgErr('')
    setImgBusy(true)
    try {
      setImage(await fileToResizedDataUrl(file))
    } catch (e) {
      setImgErr((e as Error).message)
    } finally {
      setImgBusy(false)
    }
  }

  const submit = () => {
    if (!title.trim()) return // A05: 서버도 min_length=1 로 막지만 UX상 미리 방지
    const ingredients = ingText.split('\n').map((l) => l.trim()).filter(Boolean).map(parseIngredient)
    // 앞 번호("1. ", "2) ")는 벗겨서 순수 단계 텍스트만 저장
    const steps = stepText.split('\n').map((l) => l.replace(/^\s*\d+[.)]\s*/, '').trim()).filter(Boolean)
    create.mutate({
      title: title.trim(), ingredients, steps, image_url: image ?? undefined,
      cooking_time: cookingTime || undefined, serving: serving || undefined, level_nm: level || undefined,
    }, { onSuccess: onDone })
  }

  return (
    <div>
      <label style={lab}>레시피 이름</label>
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="예: 자취생 김치볶음밥" style={inp} />

      <label style={lab}>대표 사진 <span style={{ color: '#9A9A9A', fontWeight: 400 }}>(선택)</span></label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <div style={{ width: 72, height: 72, flexShrink: 0, background: `#F0F0F0 center/cover no-repeat${image ? ` url("${image}")` : ''}`, border: '1px solid #E6E6E6', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#B5B5B5', fontSize: 22 }}>
          {!image && '＋'}
        </div>
        <div>
          <label style={{ ...ghostBtn, display: 'inline-block', padding: '8px 14px', cursor: imgBusy ? 'default' : 'pointer', opacity: imgBusy ? 0.6 : 1 }}>
            {imgBusy ? '처리 중…' : image ? '사진 변경' : '사진 선택'}
            <input type="file" accept="image/*" disabled={imgBusy} onChange={(e) => onPickImage(e.target.files?.[0])} style={{ display: 'none' }} />
          </label>
          {image && (
            <button onClick={() => setImage(null)} style={{ marginLeft: 8, padding: '8px 12px', border: '1.5px solid #E6E6E6', background: '#fff', color: '#9A9A9A', fontSize: 12.5, fontWeight: 700, cursor: 'pointer' }}>제거</button>
          )}
          <div style={{ fontSize: 11, color: '#9A9A9A', marginTop: 6 }}>업로드 시 자동으로 축소돼요.</div>
        </div>
      </div>
      {imgErr && <p style={{ color: '#F04452', fontSize: 12.5, margin: '-4px 0 10px' }}>{imgErr}</p>}

      {/* 만개 레시피와 동일한 메타(조리시간·인분·난이도) — 상세에서 칩으로 노출. 전부 선택. */}
      <label style={lab}>조리 정보 <span style={{ color: '#9A9A9A', fontWeight: 400 }}>(선택 · 만개 레시피처럼 칩으로 표시돼요)</span></label>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, margin: '6px 0 16px' }}>
        <select value={cookingTime} onChange={(e) => setCookingTime(e.target.value)} style={{ ...inp, margin: 0, background: '#fff' }}>
          <option value="">조리시간</option>
          {TIME_OPTS.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <select value={serving} onChange={(e) => setServing(e.target.value)} style={{ ...inp, margin: 0, background: '#fff' }}>
          <option value="">인분</option>
          {SERVING_OPTS.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <select value={level} onChange={(e) => setLevel(e.target.value)} style={{ ...inp, margin: 0, background: '#fff' }}>
          <option value="">난이도</option>
          {LEVEL_OPTS.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>

      <label style={lab}>재료 <span style={{ color: '#9A9A9A', fontWeight: 400 }}>(한 줄에 하나씩 · "재료 수량")</span></label>
      <textarea value={ingText} onChange={(e) => setIngText(e.target.value)} placeholder={'김치 100g\n밥 1공기\n대파 1대'} style={{ ...inp, minHeight: 76, resize: 'vertical', fontFamily: 'inherit' }} />
      <label style={lab}>조리 순서 <span style={{ color: '#9A9A9A', fontWeight: 400 }}>(한 줄에 한 단계)</span></label>
      <textarea value={stepText} onChange={(e) => setStepText(e.target.value)} placeholder={'팬에 기름을 두르고 김치를 볶는다\n밥을 넣고 함께 볶는다'} style={{ ...inp, minHeight: 90, resize: 'vertical', fontFamily: 'inherit' }} />
      {create.error && <p style={{ color: '#F04452', fontSize: 12.5, margin: '2px 0 10px' }}>{(create.error as Error).message}</p>}
      <div style={{ fontSize: 11.5, color: '#9A9A9A', margin: '0 0 12px' }}>저장 후 목록에서 <b style={{ color: '#5E5E5E' }}>공유</b>를 누르면 링크가 만들어져요.</div>
      <div style={{ display: 'flex', gap: 10 }}>
        <button onClick={onDone} style={{ ...ghostBtn, flex: 1 }}>취소</button>
        <button
          onClick={submit}
          disabled={!title.trim() || create.isPending}
          style={{ ...primaryBtn, flex: 2, opacity: !title.trim() || create.isPending ? 0.6 : 1, cursor: !title.trim() || create.isPending ? 'not-allowed' : 'pointer' }}
        >
          {create.isPending ? '저장 중…' : '레시피북에 저장'}
        </button>
      </div>
    </div>
  )
}
