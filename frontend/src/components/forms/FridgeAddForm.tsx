import { inp, lab, primaryBtn, ghostBtn } from './formStyles'

// 재료 직접 등록 (모달 콘텐츠). 저장/취소 시 onDone 호출.
export default function FridgeAddForm({ onDone }: { onDone: () => void }) {
  return (
    <div>
      <label style={lab}>재료명</label>
      <input placeholder="예: 대파 (입력 시 표준 재료 자동완성)" style={inp} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={lab}>수량</label>
          <input defaultValue="1" style={inp} />
        </div>
        <div>
          <label style={lab}>단위</label>
          <input defaultValue="단" style={inp} />
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={lab}>유통기한</label>
          <input defaultValue="2026-07-25" style={inp} />
        </div>
        <div>
          <label style={lab}>보관 위치</label>
          <input defaultValue="냉장" style={inp} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
        <button onClick={onDone} style={{ ...ghostBtn, flex: 1 }}>취소</button>
        <button onClick={onDone} style={{ ...primaryBtn, flex: 2 }}>저장</button>
      </div>
    </div>
  )
}
