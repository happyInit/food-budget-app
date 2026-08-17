// 영수증 축소 로직 테스트(vitest) — 컴포넌트/네트워크 없이 순수 함수 + 폴백 경로만.
// 🔵 이 환경은 node 라 canvas·createImageBitmap 이 **없다.** 그래서 여기서 검증할 수 있는 것은
//    ① 크기 계산 ② «브라우저 API 가 없을 때 원본을 그대로 돌려주는가» 두 가지다.
//    ②가 중요한 이유 = 축소는 **최적화지 요구사항이 아니다.** 여기서 던지면 사진을 아예
//    못 올리는 회귀가 되고, 그건 축소가 주는 이득보다 훨씬 크다.
import { describe, expect, it } from 'vitest'
import { fitWithin, shrinkReceipt } from './image'

describe('fitWithin', () => {
  it('이미 작으면 건드리지 않는다(null)', () => {
    // 🔵 재인코딩을 안 한다는 뜻 — 불필요한 손실 세대를 만들지 않는다.
    expect(fitWithin(1200, 800)).toBeNull()
    expect(fitWithin(1600, 900)).toBeNull() // 경계: 최장변 == 상한이면 그대로
  })

  it('최장변을 상한에 맞추고 비율을 지킨다', () => {
    expect(fitWithin(4000, 3000)).toEqual({ w: 1600, h: 1200 })
    expect(fitWithin(3000, 4000)).toEqual({ w: 1200, h: 1600 }) // 세로 사진
  })

  it('영수증처럼 극단적으로 긴 사진도 상한 안에 넣는다', () => {
    const got = fitWithin(1200, 9000)!
    expect(Math.max(got.w, got.h)).toBe(1600)
    expect(got.w).toBeGreaterThanOrEqual(1) // 🔴 반올림이 0 이 되면 캔버스가 죽는다
  })

  it('상한을 바꿔 부를 수 있다', () => {
    expect(fitWithin(4000, 2000, 800)).toEqual({ w: 800, h: 400 })
  })

  it('크기를 모르면 원본을 그대로 둔다', () => {
    // 🔴 0·NaN 에서 계산을 밀어붙이면 1x1 짜리를 만들어 **영수증을 지운다.**
    expect(fitWithin(0, 100)).toBeNull()
    expect(fitWithin(NaN, 100)).toBeNull()
  })
})

describe('shrinkReceipt', () => {
  const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], 'receipt.jpg', { type: 'image/jpeg' })

  it('브라우저 API 가 없으면 원본을 그대로 돌려준다', async () => {
    // node 환경 = createImageBitmap 도 document 도 없다. 던지지 않고 원본이어야 한다.
    await expect(shrinkReceipt(file)).resolves.toBe(file)
  })

  it('이미지를 열지 못해도 던지지 않는다', async () => {
    const g = globalThis as unknown as Record<string, unknown>
    g.createImageBitmap = () => Promise.reject(new Error('decode 실패'))
    g.document = { createElement: () => ({ getContext: () => null }) }
    try {
      await expect(shrinkReceipt(file)).resolves.toBe(file)
    } finally {
      delete g.createImageBitmap
      delete g.document
    }
  })
})
