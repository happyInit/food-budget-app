// 인증/예산 순수 로직 테스트 (vitest). 금액 파싱·프리셋·회원가입 검증. 리터럴로 검증.
import { describe, it, expect } from 'vitest'
import { parseAmount, presetToAmount, validateSignup } from './auth'

describe('parseAmount', () => {
  it('strips non-digits → integer won', () => {
    expect(parseAmount('300,000')).toBe(300000)
    expect(parseAmount('₩ 300,000 원')).toBe(300000)
    expect(parseAmount('')).toBe(0)
    expect(parseAmount('abc')).toBe(0)
  })
})

describe('presetToAmount', () => {
  it('N만 → 원', () => {
    expect(presetToAmount('20만')).toBe(200000)
    expect(presetToAmount('50만')).toBe(500000)
  })
})

describe('validateSignup', () => {
  it('accepts valid input (null = no error)', () => {
    expect(validateSignup({ email: 'a@b.com', password: 'hunter2!!', nickname: 'kim' })).toBe(null)
  })
  it('rejects malformed email', () => {
    expect(validateSignup({ email: 'nope', password: 'hunter2!!', nickname: 'kim' })).toMatch(/이메일/)
  })
  it('rejects password shorter than 8 (백엔드 min_length=8)', () => {
    expect(validateSignup({ email: 'a@b.com', password: 'short', nickname: 'kim' })).toMatch(/비밀번호/)
  })
  it('rejects blank nickname', () => {
    expect(validateSignup({ email: 'a@b.com', password: 'hunter2!!', nickname: '  ' })).toMatch(/닉네임/)
  })
})
