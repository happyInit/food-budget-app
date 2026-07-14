import { useNavigate } from 'react-router-dom'

export default function OcrUpload() {
  const nav = useNavigate()
  return (
    <div>
      <div style={{ fontSize: 12.5, color: '#9A9A9A', marginBottom: 10 }}>
        <span style={{ cursor: 'pointer' }} onClick={() => nav('/fridge')}>내 냉장고</span> / 영수증 OCR 등록
      </div>
      <h1 style={{ fontSize: 23, fontWeight: 800, letterSpacing: '-.5px', margin: '0 0 20px' }}>영수증으로 재고 등록</h1>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 16 }}>
        <div>
          <div onClick={() => nav('/ocr/result')} style={{ border: '2px dashed #1FA463', padding: '52px 24px', textAlign: 'center', background: '#E6F6EC', cursor: 'pointer' }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#1FA463' }}>촬영 또는 이미지 업로드</div>
            <div style={{ fontSize: 12.5, color: '#9A9A9A', marginTop: 6 }}>종이 영수증 · 이커머스 결제 캡처 지원</div>
          </div>
          <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 12, lineHeight: 1.7 }}>
            · 지원 형식: JPG, PNG (최대 10MB)<br />
            · 여러 장을 한 번에 올릴 수 있어요<br />
            · 분석 결과는 저장 전에 직접 수정할 수 있어요
          </div>
        </div>
        <div style={{ background: '#fff', border: '1px solid #E6E6E6', padding: 20 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, margin: '0 0 12px' }}>이렇게 처리돼요</h3>
          <div style={{ fontSize: 13, color: '#5E5E5E', lineHeight: 2.1 }}>
            1 이미지 업로드 → OCR 텍스트 인식<br />
            2 재료 NER → 표준 품목코드로 정규화<br />
            3 유통기한 대략 추정 (AI)<br />
            4 <b>사용자 확인·수정</b> 후 재고 반영 (자동 확정 X)<br />
            5 결제 금액 → 식비 캘린더 자동 기록
          </div>
        </div>
      </div>
    </div>
  )
}
