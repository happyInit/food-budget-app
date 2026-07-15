import { useState } from 'react'
import { primaryBtn, ghostBtn } from './formStyles'

const td: React.CSSProperties = { padding: '11px 10px', borderBottom: '1px solid #EFEFEF' }
const th: React.CSSProperties = { textAlign: 'left', padding: '8px 10px', borderBottom: '2px solid #E6E6E6', fontSize: 12, color: '#5E5E5E', fontWeight: 600 }

function store(label: string, tone: 'freeze' | 'fridge' | 'room') {
  const c = tone === 'freeze' ? { bg: '#E7EFF8', fg: '#1E5F96' } : tone === 'fridge' ? { bg: '#FCEBDD', fg: '#F26419' } : { bg: '#F4F4F4', fg: '#5E5E5E' }
  return <span style={{ padding: '2px 7px', fontSize: 11, background: c.bg, color: c.fg, fontWeight: 600 }}>{label}</span>
}

const rows: [string, string, ReturnType<typeof store>, string][] = [
  ['돼지고기 목살 300g', '7/19 (D-6)', store('냉동', 'freeze'), '5,900원'],
  ['배추김치 1kg', '8/13 (D-31)', store('냉장', 'fridge'), '6,900원'],
  ['풀무원 두부 1모', '7/16 (D-3)', store('냉장', 'fridge'), '1,990원'],
  ['계란 15구', '7/27 (D-14)', store('냉장', 'fridge'), '5,480원'],
  ['양파 1.5kg', '7/29 (D-16)', store('실온', 'room'), '3,290원'],
]

// 영수증 OCR: 업로드 → 결과 확인·확정 (2단계 모달 콘텐츠)
export default function OcrFlow({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState<'upload' | 'result'>('upload')

  if (step === 'upload')
    return (
      <div>
        <div onClick={() => setStep('result')} style={{ border: '2px dashed #F26419', padding: '52px 24px', textAlign: 'center', background: '#FCEBDD', cursor: 'pointer' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#F26419' }}>촬영 또는 이미지 업로드</div>
          <div style={{ fontSize: 12.5, color: '#9A9A9A', marginTop: 6 }}>종이 영수증 · 이커머스 결제 캡처 지원</div>
        </div>
        <div style={{ fontSize: 11.5, color: '#9A9A9A', marginTop: 12, lineHeight: 1.7 }}>
          · 지원 형식: JPG, PNG (최대 10MB)<br />
          · 여러 장을 한 번에 올릴 수 있어요<br />
          · 분석 결과는 저장 전에 직접 수정할 수 있어요
        </div>
      </div>
    )

  return (
    <div>
      <div style={{ background: '#FCEBDD', color: '#F26419', fontSize: 12.5, padding: '12px 16px', marginBottom: 16 }}>인식 결과를 확인하고 필요하면 수정하세요. 확인을 눌러야 재고·식비에 반영됩니다.</div>
      <div style={{ fontSize: 12, color: '#9A9A9A', marginBottom: 14 }}>마켓컬리 주문 · 2026.07.13 · <b style={{ color: '#1E5F96' }}>5개 인식됨</b></div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              <th style={th}>품목</th>
              <th style={th}>유통기한(추정)</th>
              <th style={th}>보관</th>
              <th style={{ ...th, textAlign: 'right' }}>가격</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const cell = i === rows.length - 1 ? { padding: '11px 10px' } : td
              return (
                <tr key={i}>
                  <td style={cell}>{r[0]}</td>
                  <td style={cell}>{r[1]}</td>
                  <td style={cell}>{r[2]}</td>
                  <td className="num" style={{ ...cell, textAlign: 'right' }}>{r[3]}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div style={{ marginTop: 16, padding: '14px 16px', background: '#FCEBDD', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <div style={{ fontSize: 12, color: '#F26419' }}>합계 → 식비 캘린더 자동 기록</div>
          <div className="num" style={{ fontSize: 20, fontWeight: 800, color: '#F26419' }}>23,560원</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setStep('upload')} style={{ ...ghostBtn, padding: '10px 14px' }}>다시 촬영</button>
          <button onClick={onDone} style={{ ...primaryBtn, padding: '10px 16px' }}>확인하고 등록</button>
        </div>
      </div>
    </div>
  )
}
