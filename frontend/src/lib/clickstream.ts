// 클릭스트림 세션 — **추천(노출)과 담기(행동)를 잇는 조인 키**.
//
// 왜 필요한가: 랭킹 학습(LambdaMART)은 "이 화면에서 뭘 골랐나"를 배운다. 서버는 추천 응답을
// activity.recipe_impression 에, 담기를 activity.user_event 에 각각 적는데, 둘을 잇는 키가
// session_id 다. 학습 SQL 이 `e.session_id = i.session_id` 로 조인한다.
//
// 🔴 그 키를 프론트가 안 보내서 조인이 통째로 실패하고 있었다 (실측 2026-08-13):
//     user_event.session_id      44건 전부 NULL
//     recipe_impression          서버가 발급한 uuid4 16개
//     교집합 0  →  양성 라벨 0  →  학습행이 320개나 쌓여도 <b>배울 게 없다</b>
//   백엔드 필드(RecommendReq.session_id · CartItemCreate.session_id)는 이미 있었다.
//
// ⚠️ 두 곳이 **조용히 메우도록** 돼 있어 3주간 아무도 몰랐다 — 추천은 서버가 uuid4 를 발급하고
//   (queries.py "없거나 형식오류면 서버가 발급(비링크)"), 담기는 NULL 로 지나간다.
//   그래서 "안 보내고 있다"는 사실이 로그 어디에도 남지 않았다.
//
// **수명 = 추천 1회**. 학습 SQL 의 그룹이 `(user_id, session_id)` 라 이게 곧 LambdaMART 의
// 그룹 1개가 된다. 탭 단위로 잡으면 여러 화면이 한 그룹으로 뭉개져 순위 학습이 망가진다.
//
// 라우트를 건너야 한다 — 추천은 Home 에서, 담기는 RecipeDetail 에서 일어난다.
// 그래서 컴포넌트 상태가 아니라 모듈 레벨에 둔다(api.ts 의 refreshInFlight 과 같은 패턴).

let current: string | null = null

/** v4 UUID. 🔴 PG 컬럼이 `uuid` 타입이라 **형식이 틀리면 담기 이벤트가 버려진다**. */
export function uuidV4(): string {
  const c = globalThis.crypto
  // randomUUID 는 **보안 컨텍스트(HTTPS·localhost)에서만** 존재한다. LAN IP 로 여는 dev 에선
  // undefined 라 그대로 부르면 추천 요청 자체가 깨진다 → 아래 폴백이 그 경우를 받는다.
  if (typeof c?.randomUUID === 'function') return c.randomUUID()

  const b = new Uint8Array(16)
  if (typeof c?.getRandomValues === 'function') c.getRandomValues(b)
  else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256)
  b[6] = (b[6] & 0x0f) | 0x40 // version 4
  b[8] = (b[8] & 0x3f) | 0x80 // variant 10
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0'))
  return [
    h.slice(0, 4).join(''), h.slice(4, 6).join(''), h.slice(6, 8).join(''),
    h.slice(8, 10).join(''), h.slice(10, 16).join(''),
  ].join('-')
}

/** 추천 요청 시작 — 새 세션을 발급하고 돌려준다. 이후 담기가 이 값을 따라붙는다. */
export function startRecommendSession(): string {
  current = uuidV4()
  return current
}

/** 담기 시점의 현재 세션. 추천을 한 번도 안 거쳤으면 undefined(= 서버가 NULL 로 받는다). */
export function currentSession(): string | undefined {
  return current ?? undefined
}

/** 테스트 전용 — 모듈 상태 초기화. */
export function _resetSession(): void {
  current = null
}
