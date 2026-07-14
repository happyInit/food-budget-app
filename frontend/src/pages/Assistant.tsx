import { chat } from '../lib/mock'

export default function Assistant() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-tight md:text-[26px]">대화형 어시스턴트</h1>
      <p className="mt-1 text-sm text-sub">재고·예산·시세를 알고 있는 어시스턴트예요. 식단·장보기를 대화로 짜보세요.</p>
      <div className="mt-5 flex h-[440px] flex-col rounded-2xl border border-line bg-surface p-4 shadow-sm">
        <div className="flex-1 space-y-3 overflow-y-auto pr-1">
          {chat.map((m, i) => (
            <div
              key={i}
              className={`max-w-[80%] whitespace-pre-line rounded-2xl px-4 py-3 text-[13.5px] leading-relaxed ${
                m.me ? 'ml-auto rounded-br-md bg-brand text-white' : 'rounded-bl-md border border-line bg-cream'
              }`}
            >
              {m.text}
            </div>
          ))}
        </div>
        <div className="mt-3 flex gap-2 border-t border-line/60 pt-3">
          <input
            className="flex-1 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm outline-none focus:border-brand"
            placeholder="메시지 입력…"
          />
          <button className="rounded-xl bg-brand px-4 font-bold text-white">보내기</button>
        </div>
      </div>
    </div>
  )
}
