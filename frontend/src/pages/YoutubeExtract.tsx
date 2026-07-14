import { useNavigate } from 'react-router-dom'
import { Card, Chip, Thumb, Button } from '../components/ui'
import { inputCls } from './auth/AuthLayout'

export default function YoutubeExtract() {
  const nav = useNavigate()
  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">YouTube 레시피 추출</h1>
      <p className="mt-1 text-sm text-sub">요리 영상 URL을 넣으면 재료·분량·조리 단계를 뽑아 레시피북에 담아요.</p>
      <div className="mt-4 flex gap-2">
        <input className={inputCls} defaultValue="https://youtube.com/watch?v=..." />
        <Button className="shrink-0">추출하기</Button>
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-2 md:items-start">
        <Card className="p-5">
          <div className="grid h-44 place-items-center rounded-xl bg-[#111] text-5xl text-white">▶</div>
          <div className="mt-3 font-extrabold">백종원의 초간단 계란찜</div>
          <div className="text-[13px] text-sub">4분 12초 · 조리 영상</div>
          <div className="mt-3 rounded-xl bg-brand-weak/40 px-3 py-2.5 text-xs text-brand">
            ✨ Gemini 멀티모달로 추출 후, 자체 <b>한식 재료 NER</b>로 표준 품목·현재가와 매칭했어요.
          </div>
        </Card>
        <Card className="p-5">
          <b className="text-[15px]">
            추출 결과 <span className="text-xs font-normal text-faint">· 수정 후 저장</span>
          </b>
          {[
            ['🥚', '계란 3개', '00:45 · 표준: 계란', '₩1,100', ''],
            ['🧂', '새우젓 1스푼', '01:10', '', '확인'],
            ['🧅', '대파 약간', '01:30 · 보유', '', '보유'],
          ].map(([e, n, s, p, tg]) => (
            <div key={n} className="flex items-center gap-3 border-b border-line/60 py-2.5 last:border-0">
              <Thumb className="h-9 w-9 text-lg">{e}</Thumb>
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] font-bold">{n}</div>
                <div className="text-xs text-sub">{s}</div>
              </div>
              {p ? (
                <span className="num text-sm font-extrabold">{p}</span>
              ) : (
                <Chip tone={tg === '보유' ? 'brand' : 'warn'}>{tg}</Chip>
              )}
            </div>
          ))}
          <Button size="lg" className="mt-3.5 w-full" onClick={() => nav('/recipebook')}>
            레시피북에 저장
          </Button>
        </Card>
      </div>
    </div>
  )
}
