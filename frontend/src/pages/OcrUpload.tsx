import { useNavigate } from 'react-router-dom'
import { Card, Thumb, Button } from '../components/ui'

export default function OcrUpload() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">영수증 등록</h1>
      <p className="mt-1 text-sm text-sub">종이 영수증을 촬영하거나 이커머스 캡처를 올리면 재료·식비를 자동으로 읽어요.</p>
      <div className="mt-5 grid gap-4 md:grid-cols-2 md:items-start">
        <Card className="p-5">
          <div className="grid place-items-center rounded-2xl border-2 border-dashed border-line bg-cream py-12 text-center text-sub">
            <div className="text-4xl">🧾</div>
            <div className="mt-2.5 font-extrabold text-ink">여기로 끌어다 놓기</div>
            <div className="mt-1 text-sm">
              또는 <b className="text-brand">파일 선택</b> · 카메라 촬영
            </div>
            <div className="mt-3 text-xs text-faint">JPG · PNG · 최대 10MB</div>
          </div>
          <Button size="lg" className="mt-4 w-full" onClick={() => nav('/ocr/result')}>
            분석 요청
          </Button>
        </Card>
        <Card className="p-5">
          <b className="mb-2 block">잘 나온 사진의 조건</b>
          {[
            ['💡', '밝은 곳에서 반듯하게', '그림자·구겨짐이 적을수록 정확해요'],
            ['🔍', '품목·금액이 보이게', '상단 매장명 ~ 하단 합계까지'],
            ['🛒', '이커머스 캡처도 OK', '마켓컬리·오아시스 주문내역 스크린샷'],
          ].map(([e, t, s]) => (
            <div key={t} className="flex items-center gap-3 py-2.5">
              <Thumb>{e}</Thumb>
              <div>
                <div className="text-sm font-bold">{t}</div>
                <div className="text-xs text-sub">{s}</div>
              </div>
            </div>
          ))}
          <div className="mt-2 rounded-xl bg-brand-weak/40 px-3 py-2.5 text-xs text-brand">
            🔒 이미지는 분석에만 쓰이고 원본은 저장하지 않아요.
          </div>
        </Card>
      </div>
    </div>
  )
}
