import { useState } from 'react'
import { inp, lab, primaryBtn, ghostBtn } from './formStyles'

// 레시피 직접 작성 (모달 콘텐츠) → 내 레시피북에 저장.
export default function RecipeWriteForm({ onDone }: { onDone: () => void }) {
  const [pub, setPub] = useState(false)
  return (
    <div>
      <label style={lab}>레시피 이름</label>
      <input placeholder="예: 자취생 김치볶음밥" style={inp} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={lab}>조리 시간</label>
          <input placeholder="예: 15분" style={inp} />
        </div>
        <div>
          <label style={lab}>인분</label>
          <input placeholder="예: 1인분" style={inp} />
        </div>
      </div>
      <label style={lab}>재료 (한 줄에 하나씩)</label>
      <textarea placeholder={'김치 100g\n밥 1공기\n대파 1대'} style={{ ...inp, minHeight: 76, resize: 'vertical', fontFamily: 'inherit' }} />
      <label style={lab}>조리 순서</label>
      <textarea placeholder={'1. 팬에 기름을 두르고 김치를 볶는다\n2. 밥을 넣고 함께 볶는다'} style={{ ...inp, minHeight: 90, resize: 'vertical', fontFamily: 'inherit' }} />
      <label style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '2px 0 18px', cursor: 'pointer' }}>
        <input type="checkbox" checked={pub} onChange={(e) => setPub(e.target.checked)} />
        <span style={{ fontSize: 13, color: '#5E5E5E' }}>레시피북 공개 (다른 사용자가 스크랩 가능)</span>
      </label>
      <div style={{ display: 'flex', gap: 10 }}>
        <button onClick={onDone} style={{ ...ghostBtn, flex: 1 }}>취소</button>
        <button onClick={onDone} style={{ ...primaryBtn, flex: 2 }}>레시피북에 저장</button>
      </div>
    </div>
  )
}
