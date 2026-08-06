// 외부 링크 href 안전화 — http/https 스킴만 통과시킨다.
// 유저 입력 URL(레시피 source_url 등)이 `javascript:`·`data:` 스킴이면 클릭 시 오리진 컨텍스트에서
// 스크립트가 실행돼 localStorage 토큰이 유출될 수 있다(self/stored XSS) → 렌더 전에 차단한다.
// 안전하지 않거나 파싱 불가하면 undefined(호출측이 링크를 렌더하지 않음).
export function safeHttpUrl(raw: string | null | undefined): string | undefined {
  if (!raw) return undefined
  try {
    const u = new URL(raw)
    return u.protocol === 'http:' || u.protocol === 'https:' ? u.href : undefined
  } catch {
    return undefined
  }
}
