// 소셜 로그인(카카오·구글) 시작/검증 헬퍼.
// - client_id 는 공개값(브라우저 authorize URL 에 노출됨) → VITE_ env 로 주입. client_secret 은 백엔드 전용(여기 없음).
// - redirect_uri 는 현재 origin 기반 → dev(localhost:5173)·운영(app.mealbong.cloud) 자동 정합
//   (양쪽 다 provider 콘솔에 등록돼 있어야 함). 이 값은 콜백에서 백엔드 교환에도 그대로 전달.
// - state = CSRF 방지. sessionStorage 왕복으로 대조.
export type Provider = 'kakao' | 'google'

const CLIENT_ID: Record<Provider, string | undefined> = {
  kakao: import.meta.env.VITE_KAKAO_REST_KEY as string | undefined,
  google: import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined,
}
const AUTHORIZE: Record<Provider, string> = {
  kakao: 'https://kauth.kakao.com/oauth/authorize',
  google: 'https://accounts.google.com/o/oauth2/v2/auth',
}
const stateKey = (p: Provider) => `oauth_state_${p}`

export const redirectUri = (provider: Provider) =>
  `${window.location.origin}/auth/${provider}/callback`

// provider 동의화면으로 리다이렉트. 미설정(client_id 없음)이면 안내 문자열을 반환하고 리다이렉트하지 않는다.
export function startOAuth(provider: Provider): string | null {
  const clientId = CLIENT_ID[provider]
  if (!clientId) return `${provider === 'kakao' ? '카카오' : '구글'} 로그인이 아직 설정되지 않았어요.`
  const state = crypto.randomUUID()
  sessionStorage.setItem(stateKey(provider), state)
  const p = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri(provider),
    response_type: 'code',
    state,
  })
  if (provider === 'google') p.set('scope', 'openid email profile')
  window.location.href = `${AUTHORIZE[provider]}?${p.toString()}`
  return null
}

// 콜백에서 state 1회용 대조 — 일치해야 code 교환을 진행한다.
export function consumeState(provider: Provider, got: string | null): boolean {
  const want = sessionStorage.getItem(stateKey(provider))
  sessionStorage.removeItem(stateKey(provider))
  return !!want && want === got
}
