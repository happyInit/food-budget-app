import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getToken } from '../lib/api'
import { useLogin, useLogout } from '../lib/queries'
import { clearPrewarmed, guestCredentials, isPrewarmed, markPrewarmed } from '../lib/guest'

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
  // 🔴 "예열된 게스트"는 로그인한 사용자로 치지 않는다 — 그래야 재방문해도 헤더가
  //    「로그인 / 체험해보기」로 남고, 방문자가 자기가 로그인했다고 오해하지 않는다.
  const [authed, setAuthed] = useState(() => !!getToken() && !isPrewarmed())

  // ── 「체험해보기」 예열 ────────────────────────────────────────────────────
  // 포트폴리오 방문자가 로그인 없이 바로 안을 볼 수 있어야 한다. 그래서 랜딩이 뜨는 동안
  // 게스트 세션을 **미리** 만들어 두고, 버튼을 누르면 왕복 없이 곧장 /home 으로 보낸다.
  //
  // 🔴 예열에 성공해도 `authed` 를 켜지 않는다 — 켜면 헤더가 「로그아웃」으로 바뀌어
  //    처음 온 사람이 *"내가 언제 로그인했지"* 로 읽는다. 세션은 있되 화면은 그대로 둔다.
  // 🔴 이미 토큰이 있으면(직접 로그인했거나 재방문) 건드리지 않는다 — 남의 세션을
  //    게스트로 덮어쓰면 장바구니·예산이 통째로 바뀐 것처럼 보인다.
  const loginM = useLogin()
  const [warm, setWarm] = useState(false)
  const fired = useRef(false)   // StrictMode 의 두 번 호출을 막는다

  useEffect(() => {
    if (fired.current || authed) return
    fired.current = true
    // 이미 예열된 세션이 있으면 재사용한다 — 방문할 때마다 새 게스트를 잡으면
    // 아까 담아 둔 장바구니가 매번 사라져 "동작이 안 되는 것"처럼 보인다.
    if (getToken() && isPrewarmed()) { setWarm(true); return }
    loginM.mutate(guestCredentials(), {
      onSuccess: () => { markPrewarmed(); setWarm(true) },
      // 실패해도 조용히 둔다 — 버튼이 /guest 로 가서 거기서 다시 시도하고,
      // 그 화면은 실패 시 이메일 로그인 안내까지 갖고 있다.
      onError: () => setWarm(false),
    })
  }, [])

  // 예열됐으면 곧장 홈, 아니면 /guest 가 로그인을 맡는다.
  const goDemo = () => nav(warm ? '/home' : '/guest')

  const onLogout = async () => {
    await logout()
    clearPrewarmed()
    setAuthed(false)
    setWarm(false)
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
                {/* 헤더는 sticky 라 어디까지 스크롤해도 체험 진입이 손에 닿는다. */}
                <button onClick={goDemo} className="rounded-lg bg-brand px-4 py-2.5 text-sm font-bold text-white transition hover:bg-brand-dark">
                  체험해보기
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
                <>
                  {/* 포트폴리오 1순위 동선 — 가입·로그인 없이 바로 안을 보여준다. */}
                  <button onClick={goDemo} className="rounded-lg bg-brand px-6 py-3.5 font-bold text-white transition hover:bg-brand-dark">
                    체험해보기
                  </button>
                  <button onClick={() => nav('/signup')} className="rounded-lg border border-white/40 bg-white/10 px-6 py-3.5 font-bold text-white backdrop-blur transition hover:bg-white/20">
                    시작하기
                  </button>
                </>
              )}
            </div>
            {!authed && (
              <p className="mt-3 text-sm text-white/70">체험 계정으로 둘러볼 수 있어요 — 가입·로그인 없이 바로.</p>
            )}
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
