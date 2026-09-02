// 체험(게스트) 계정 규칙 — `/guest` 자동로그인과 랜딩 「체험해보기」가 함께 쓴다.
//
// 계정은 guest001~guest999 (비밀번호 = 아이디와 동일) 가 DB 에 실재한다.
// 🔴 번호를 무작위로 뽑는 이유: 같은 링크를 여러 명이 동시에 연다.
//    한 계정을 공유하면 서로의 장바구니·예산이 섞여서 화면이 엉망이 된다.
const GUEST_MIN = 1
const GUEST_MAX = 999

/** 지정 번호(1~999)가 유효하면 그것을, 아니면 무작위로 하나 뽑아 3자리로 만든다. */
export function pickGuestNo(asked?: string | null): string {
  const n = Number(asked)
  const picked =
    Number.isInteger(n) && n >= GUEST_MIN && n <= GUEST_MAX
      ? n
      : GUEST_MIN + Math.floor(Math.random() * (GUEST_MAX - GUEST_MIN + 1))
  return String(picked).padStart(3, '0')
}

/** 로그인 API 에 그대로 넘길 자격증명. */
export function guestCredentials(asked?: string | null): { email: string; password: string } {
  const id = pickGuestNo(asked)
  return { email: `guest${id}@gmail.com`, password: `guest${id}` }
}

// ── 예열 표시 ─────────────────────────────────────────────────────────────────
// 🔴 랜딩의 배경 예열은 토큰을 localStorage 에 남긴다. 그래서 표시가 없으면 **재방문 때**
//    랜딩이 "로그인된 사용자"로 보고 헤더를 「로그아웃」으로 바꾼다 — 방문자는 로그인한
//    적이 없으므로 *"내가 언제?"* 가 된다. 이 키가 그 세션의 출처를 기억한다.
// 🔵 사람이 실제로 로그인·가입하면 지운다(그 세션은 더 이상 예열이 아니다).
const PREWARM_KEY = 'mp_guest_prewarm'

export const markPrewarmed = () => {
  try { localStorage.setItem(PREWARM_KEY, '1') } catch { /* 사생활 모드 등 — 없어도 동작한다 */ }
}
export const isPrewarmed = () => {
  try { return localStorage.getItem(PREWARM_KEY) === '1' } catch { return false }
}
export const clearPrewarmed = () => {
  try { localStorage.removeItem(PREWARM_KEY) } catch { /* 위와 같다 */ }
}
