// 클릭스트림 세션 — 조인 키가 실제로 성립하는지 검증한다.
//
// 이 테스트가 지키는 것은 **조인 가능성**이다. 하나라도 깨지면 학습 라벨이 다시 0이 된다:
//   ① 형식이 UUID 여야 한다        (PG 컬럼이 uuid 타입 — 틀리면 담기 이벤트가 버려진다)
//   ② 추천마다 새 세션이어야 한다   (그룹 = (user_id, session_id) = 화면 1개)
//   ③ 담기가 그 세션을 그대로 써야 한다 (라우트를 건너서)
//   ④ 보안 컨텍스트가 아니어도 동작해야 한다 (randomUUID 부재 폴백)
import { afterEach, describe, expect, it, vi } from 'vitest'

import { _resetSession, currentSession, startRecommendSession, uuidV4 } from './clickstream'

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

afterEach(() => {
  _resetSession()
  vi.unstubAllGlobals()
})

describe('uuidV4', () => {
  it('① UUID v4 형식이다 — PG uuid 컬럼이 받는 형식', () => {
    expect(uuidV4()).toMatch(UUID_V4)
  })

  it('④ randomUUID 가 없어도(비보안 컨텍스트) 유효한 UUID 를 만든다', () => {
    // LAN IP 로 여는 dev 는 보안 컨텍스트가 아니라 crypto.randomUUID 가 undefined 다.
    // 폴백이 없으면 여기서 던져서 **추천 요청 자체가 깨진다**.
    vi.stubGlobal('crypto', { getRandomValues: (b: Uint8Array) => b.fill(0xab) })
    const v = uuidV4()
    expect(v).toMatch(UUID_V4)
    expect(v[14]).toBe('4') // version nibble
  })

  it('④ crypto 가 아예 없어도 형식을 지킨다', () => {
    vi.stubGlobal('crypto', undefined)
    expect(uuidV4()).toMatch(UUID_V4)
  })

  it('서로 다른 값을 만든다', () => {
    expect(uuidV4()).not.toBe(uuidV4())
  })
})

describe('세션 수명', () => {
  it('추천 전에는 세션이 없다 — 담기는 undefined(서버가 NULL 로 받는다)', () => {
    expect(currentSession()).toBeUndefined()
  })

  it('③ 담기가 직전 추천의 세션을 그대로 쓴다 — 이게 조인의 전부다', () => {
    const s = startRecommendSession()
    expect(currentSession()).toBe(s)
    expect(s).toMatch(UUID_V4)
  })

  it('② 추천마다 새 세션 — 화면 1개 = 학습 그룹 1개', () => {
    const first = startRecommendSession()
    const second = startRecommendSession()
    expect(second).not.toBe(first)
    expect(currentSession()).toBe(second) // 담기는 항상 최신 화면을 따라간다
  })

  it('세션이 라우트 이동을 건넌다 — 모듈 레벨이라 컴포넌트 언마운트와 무관', () => {
    const s = startRecommendSession()
    // Home 언마운트 → RecipeDetail 마운트를 흉내낼 것도 없다: 모듈 상태는 그대로다.
    expect(currentSession()).toBe(s)
  })
})
