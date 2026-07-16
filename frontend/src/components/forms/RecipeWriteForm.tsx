import { useState } from 'react'
import { inp, lab, primaryBtn, ghostBtn } from './formStyles'
import { useCreateMyRecipe } from '../../lib/queries'
import type { UserRecipeIngredient } from '../../lib/api'

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
  const [ingText, setIngText] = useState('')
  const [stepText, setStepText] = useState('')

  const submit = () => {
    if (!title.trim()) return // A05: 서버도 min_length=1 로 막지만 UX상 미리 방지
    const ingredients = ingText.split('\n').map((l) => l.trim()).filter(Boolean).map(parseIngredient)
    // 앞 번호("1. ", "2) ")는 벗겨서 순수 단계 텍스트만 저장
    const steps = stepText.split('\n').map((l) => l.replace(/^\s*\d+[.)]\s*/, '').trim()).filter(Boolean)
    create.mutate({ title: title.trim(), ingredients, steps }, { onSuccess: onDone })
  }

  return (
    <div>
      <label style={lab}>레시피 이름</label>
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="예: 자취생 김치볶음밥" style={inp} />
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
