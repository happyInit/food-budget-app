// 데이터 페칭 = React Query 단일화. 캐시 키·staleTime을 여기서 일괄 관리.
// 원칙: 정적(레시피)=길게 · mutable(가격)=짧게. 상세는 hover prefetch로 즉시 진입.
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addPantryItem, deletePantryItem, getExpiring, getHotdeals, getPantryItems,
  getRecipe, getRecommend, patchPantryItem, searchRecipes,
} from './api'
import type { PantryAddBody, PantryPatchBody } from './types'

// 데이터 성격별 신선도(ms)
export const STALE = {
  recipe: 30 * 60 * 1000, // 레시피(크롤링 정적) — 30분
  price: 2 * 60 * 1000, // 가격·추천·핫딜(자주 변함) — 2분
  pantry: 60 * 1000, // 재고(유저 mutable) — 뮤테이션 시 무효화, staleTime은 짧게
} as const

const PAGE_SIZE = 24

export type RecipeFilters = { cooking_time?: string; level?: string }

// 검색 캐시 키 — 검색어·필터가 바뀌면 새 키(→ 새 목록), placeholderData로 이전 결과 유지
const recipesKey = (q: string, f: RecipeFilters) =>
  ['recipes', q, f.cooking_time ?? '', f.level ?? ''] as const

// 레시피 검색(무한스크롤). 페이지 캐시 + 필터 전환 시 이전 결과 유지.
export function useRecipeSearch(q: string, f: RecipeFilters) {
  return useInfiniteQuery({
    queryKey: recipesKey(q, f),
    queryFn: ({ pageParam }) => searchRecipes(q, pageParam, PAGE_SIZE, f),
    initialPageParam: 1,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.recipes.length, 0)
      return loaded < last.total ? pages.length + 1 : undefined
    },
    staleTime: STALE.recipe,
    placeholderData: keepPreviousData,
  })
}

// 레시피 상세 — 재방문 시 캐시 즉시(30분). hover로 미리 당겨오면 클릭 즉시.
export function useRecipe(id: number) {
  return useQuery({
    queryKey: ['recipe', id],
    queryFn: () => getRecipe(id),
    staleTime: STALE.recipe,
    enabled: Number.isFinite(id),
  })
}

// 카드 hover 시 상세를 미리 fetch — 클릭 전에 캐시에 적재.
export function usePrefetchRecipe() {
  const qc = useQueryClient()
  return (id: number) =>
    qc.prefetchQuery({ queryKey: ['recipe', id], queryFn: () => getRecipe(id), staleTime: STALE.recipe })
}

// 홈 티저(검색 상위 N)
export function useRecipeTeaser(size = 3) {
  return useQuery({
    queryKey: ['recipeTeaser', size],
    queryFn: () => searchRecipes('', 1, size),
    staleTime: STALE.recipe,
  })
}

export function useHotdeals(limit = 24) {
  return useQuery({ queryKey: ['hotdeals', limit], queryFn: () => getHotdeals(limit), staleTime: STALE.price })
}

export function useRecommend(limit = 20) {
  return useQuery({ queryKey: ['recommend', limit], queryFn: () => getRecommend(limit), staleTime: STALE.price })
}

// ── Pantry (#11·#15 조회 / #12·#13·#14 뮤테이션) ──
// 캐시 키는 ['pantry', …] 접두어 → 뮤테이션 성공 시 ['pantry'] 하나로 목록·임박 모두 무효화.
const PANTRY_KEY = ['pantry'] as const

export function usePantryItems() {
  return useQuery({ queryKey: ['pantry', 'items'], queryFn: getPantryItems, staleTime: STALE.pantry })
}

export function useExpiring(withinDays = 3) {
  return useQuery({
    queryKey: ['pantry', 'expiring', withinDays],
    queryFn: () => getExpiring(withinDays),
    staleTime: STALE.pantry,
  })
}

export function useAddPantryItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PantryAddBody) => addPantryItem(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: PANTRY_KEY }),
  })
}

export function usePatchPantryItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: PantryPatchBody }) => patchPantryItem(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: PANTRY_KEY }),
  })
}

export function useDeletePantryItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deletePantryItem(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: PANTRY_KEY }),
  })
}
