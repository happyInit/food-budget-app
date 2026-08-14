import { describe, expect, it } from 'vitest'

import { normalizeRumPath } from './rum'

describe('normalizeRumPath', () => {
  it('keeps static application routes unchanged', () => {
    expect(normalizeRumPath('/mealplan')).toBe('/mealplan')
  })

  it('removes dynamic identifiers from RUM route dimensions', () => {
    expect(normalizeRumPath('/recipes/123')).toBe('/recipes/:id')
    expect(normalizeRumPath('/recipebook/456')).toBe('/recipebook/:id')
    expect(normalizeRumPath('/shared/private-token')).toBe('/shared/:token')
  })
})
