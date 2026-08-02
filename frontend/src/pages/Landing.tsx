import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getToken } from '../lib/api'
import { useLogout } from '../lib/queries'

const STEPS = [
  {
    n: 'STEP 01',
    title: '영수증 한 장이면 재고 완성',
    desc: '장 본 영수증을 찍으면 냉장고 재고가 자동으로 채워져요.',
    img: 'https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=800&q=80',
  },
  {
    n: 'STEP 02',
    title: '있는 재료로 뭐 해먹을지',
    desc: '냉장고 재료·임박 순위·예산을 반영해 오늘의 레시피를 추천해요.',
    img: 'https://images.unsplash.com/photo-1547592166-23ac45744acd?w=800&q=80',
  },
  {
    n: 'STEP 03',
    title: '예산을 넘지 않게 장보기',
    desc: '부족한 재료를 마트 최저가로 담고 예산 대비 비용을 미리 확인해요.',
    img: 'https://images.unsplash.com/photo-1512852939750-1305098529bf?w=800&q=80',
  },
]

export default function Landing() {
  const nav = useNavigate()
  const logout = useLogout()
  // 세션 확인 — 토큰 존재 여부를 로컬 상태로 잡아 로그아웃 시 즉시 재렌더.
  const [authed, setAuthed] = useState(() => !!getToken())

  const onLogout = async () => {
    await logout()
    setAuthed(false)
  }

  return (
    <div className="min-h-screen bg-cream">
      {/* 헤더 */}
      <header className="sticky top-0 z-20 border-b border-line bg-cream/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
          <div className="flex items-center gap-2">
            <img src="/icons/app-icon.png" alt="밀플래닝" className="h-9 w-9 rounded-xl object-cover" />
            <span className="text-xl font-extrabold tracking-tight text-brand">밀플래닝</span>
          </div>
          <div className="flex items-center gap-5">
            {authed ? (
              <>
                <a onClick={() => nav('/home')} className="cursor-pointer text-sm font-semibold text-sub hover:text-ink">홈으로</a>
                <button onClick={onLogout} className="rounded-lg border border-line bg-surface px-4 py-2.5 text-sm font-bold text-sub transition hover:text-ink">
                  로그아웃
                </button>
              </>
            ) : (
              <>
                <a onClick={() => nav('/login')} className="cursor-pointer text-sm font-semibold text-sub hover:text-ink">로그인</a>
                <button onClick={() => nav('/signup')} className="rounded-lg bg-brand px-4 py-2.5 text-sm font-bold text-white transition hover:bg-brand-dark">
                  시작하기
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* 히어로 */}
      <section className="relative flex h-[600px] items-center overflow-hidden">
        <img
          src="https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=1600&q=80"
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-black/75 via-black/45 to-black/10" />
        <div className="relative mx-auto w-full max-w-6xl px-6">
          <div className="max-w-xl text-white">
            <span className="mb-5 inline-block rounded-md bg-black/45 px-3 py-1.5 text-xs font-semibold text-white/90">
              한 달 식비, 이제 간단하게
            </span>
            {/* 하드코딩 <br> 대신 구절을 nowrap 으로 묶는다 → 폭에 따라 브라우저가 줄 수를
                자동 결정(넓으면 1~2줄·좁으면 3줄), 단 구절은 절대 안 쪼개짐. 균형/한글 어절은 전역 h1 규칙. */}
            <h1 className="mb-5 text-5xl font-extrabold leading-[1.2] tracking-tight">
              <span className="whitespace-nowrap">냉장고 속 재료로</span>{' '}
              <span className="whitespace-nowrap">예산 안에서</span>{' '}
              <span className="whitespace-nowrap">해먹는 가장 쉬운 방법</span>
            </h1>
            <p className="mb-8 max-w-md text-base leading-relaxed text-white/85">
              영수증을 찍으면 재고가 채워지고, 있는 재료로 만들 레시피를 추천받고, 장보기 전에 예산까지 맞춰줘요.
            </p>
            <div className="flex gap-3">
              {authed ? (
                <button onClick={() => nav('/home')} className="rounded-lg bg-brand px-6 py-3.5 font-bold text-white transition hover:bg-brand-dark">
                  홈으로 가기
                </button>
              ) : (
                <button onClick={() => nav('/signup')} className="rounded-lg bg-brand px-6 py-3.5 font-bold text-white transition hover:bg-brand-dark">
                  시작하기
                </button>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* WHY 섹션 */}
      <section className="py-24">
        <div className="mx-auto max-w-6xl px-6 text-center">
          <div className="mb-3 text-sm font-bold tracking-wide text-brand">WHY 밀플래닝</div>
          <h2 className="mb-14 text-3xl font-extrabold tracking-tight">
            장보기부터 지출까지, 하나의 흐름으로
          </h2>
          <div className="grid gap-7 text-left md:grid-cols-3">
            {STEPS.map((s) => (
              <div
                key={s.n}
                className="zoom-wrap overflow-hidden rounded-2xl border border-line bg-surface shadow-sm"
              >
                <img src={s.img} alt="" loading="lazy" className="zoom h-52 w-full object-cover" />
                <div className="p-6">
                  <div className="mb-2 text-xs font-bold tracking-wide text-brand">{s.n}</div>
                  <div className="text-lg font-bold">{s.title}</div>
                  <p className="mt-2 text-sm leading-relaxed text-sub">{s.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
