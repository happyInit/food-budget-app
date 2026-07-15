// 인증/예산 순수 로직 — React·네트워크 무관(vitest로 test-first).
// 서버 검증(account Pydantic)을 UX상 미리 반영하되, 최종 판정은 서버가 한다(A05).

// '300,000'·'₩ 300,000 원' → 300000. 숫자 없으면 0.
export function parseAmount(s: string): number {
  const digits = s.replace(/[^\d]/g, '')
  return digits ? parseInt(digits, 10) : 0
}

// 프리셋 라벨 'N만' → 원(N*10000). '30만' → 300000.
export function presetToAmount(label: string): number {
  return parseInt(label, 10) * 10000
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

// 회원가입 입력 검증 — 첫 오류 메시지 or null(통과). 백엔드: email · password 8~100 · nickname 1~30.
export function validateSignup(f: { email: string; password: string; nickname: string }): string | null {
  if (!EMAIL_RE.test(f.email.trim())) return '올바른 이메일을 입력해주세요'
  if (f.password.length < 8 || f.password.length > 100) return '비밀번호는 8자 이상이어야 해요'
  const nick = f.nickname.trim()
  if (nick.length < 1) return '닉네임을 입력해주세요'
  if (nick.length > 30) return '닉네임은 30자 이하로 입력해주세요'
  return null
}
