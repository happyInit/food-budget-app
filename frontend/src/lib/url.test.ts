// safeHttpUrl — 스킴 화이트리스트(XSS 방어) 테스트 (vitest).
import { describe, it, expect } from 'vitest'
import { safeHttpUrl } from './url'

describe('safeHttpUrl', () => {
  it('http/https 는 통과(정규화된 href)', () => {
    expect(safeHttpUrl('https://www.youtube.com/watch?v=abc')).toBe('https://www.youtube.com/watch?v=abc')
    expect(safeHttpUrl('http://example.com/')).toBe('http://example.com/')
  })

  it('javascript:·data: 등 위험 스킴은 차단(undefined)', () => {
    expect(safeHttpUrl('javascript:alert(document.cookie)')).toBeUndefined()
    expect(safeHttpUrl('  javascript:alert(1)')).toBeUndefined()          // 앞 공백은 URL이 트림 → 여전히 차단
    expect(safeHttpUrl('data:text/html,<script>alert(1)</script>')).toBeUndefined()
    expect(safeHttpUrl('vbscript:msgbox(1)')).toBeUndefined()
  })

  it('빈값·파싱불가·스킴없음은 undefined', () => {
    expect(safeHttpUrl('')).toBeUndefined()
    expect(safeHttpUrl(null)).toBeUndefined()
    expect(safeHttpUrl(undefined)).toBeUndefined()
    expect(safeHttpUrl('not a url')).toBeUndefined()
    expect(safeHttpUrl('//evil.com')).toBeUndefined()                     // 스킴 없음 → 파싱 실패
  })
})
