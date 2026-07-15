// 데이터 페칭 = React Query 단일화. 캐시 키·staleTime을 여기서 일괄 관리.
// 원칙: 정적(레시피)=길게 · mutable(가격)=짧게. 상세는 hover prefetch로 즉시 진입.
import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import {
  addBookmark,
  addCartItem,
  addExpense,
  checkoutCart,
  deleteCartItem,
  getCalendar,
  getCart,
  getExpenseSummary,
  getHotdeals,
  getRecipe,
  getRecommend,
  listBookmarks,
  listNotifications,
  markNotificationRead,
  recommendMeals,
  removeBookmark,
  searchRecipes,
  type CartItemCreate,
  type ExpenseCreate,
} from './api'

// 데이터 성격별 신선도(ms)
export const STALE = {
  recipe: 30 * 60 * 1000, // 레시피(크롤링 정적) — 30분
  price: 2 * 60 * 1000, // 가격·추천·핫딜(자주 변함) — 2분
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

// ── Dev B 백엔드 (recipebook·mealplan·notify, PR #70) ──────────────────────
// OLTP(유저 소유 데이터)라 캐시는 짧게 두고, 변경(mutation) 후 관련 키를 invalidate.
export const KEYS = {
  bookmarks: ['bookmarks'] as const,
  cart: ['cart'] as const,
  notifications: (unread: boolean) => ['notifications', unread] as const,
  expenseCalendar: (month: string) => ['expense', 'calendar', month] as const,
  expenseSummary: (month: string) => ['expense', 'summary', month] as const,
  mealRecommend: ['mealRecommend'] as const,
}
const OLTP_STALE = 30 * 1000 // 유저 데이터 — 30초

// 레시피북 북마크 (#20~22)
export function useBookmarks() {
  return useQuery({ queryKey: KEYS.bookmarks, queryFn: listBookmarks, staleTime: OLTP_STALE })
}
export function useAddBookmark() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (recipe_id: number) => addBookmark(recipe_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.bookmarks }),
  })
}
export function useRemoveBookmark() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (bookmark_id: number) => removeBookmark(bookmark_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.bookmarks }),
  })
}

// 장바구니 (#33~36)
export function useCart() {
  return useQuery({ queryKey: KEYS.cart, queryFn: getCart, staleTime: OLTP_STALE })
}
export function useAddCartItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CartItemCreate) => addCartItem(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.cart }),
  })
}
// 여러 재료를 한 번에 담기 (레시피 상세 → 장바구니). 병렬 POST 후 1회 invalidate.
export function useAddCartItems() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (items: CartItemCreate[]) => Promise.all(items.map(addCartItem)),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.cart }),
  })
}
export function useDeleteCartItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deleteCartItem(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.cart }),
  })
}
export function useCheckout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => checkoutCart(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.cart })
      qc.invalidateQueries({ queryKey: ['expense'] }) // checkout이 지출을 만든다 → 캘린더·요약 갱신
    },
  })
}

// 식비 (#38~40)
export function useExpenseCalendar(month: string) {
  return useQuery({
    queryKey: KEYS.expenseCalendar(month),
    queryFn: () => getCalendar(month),
    staleTime: OLTP_STALE,
  })
}
export function useExpenseSummary(month: string) {
  return useQuery({
    queryKey: KEYS.expenseSummary(month),
    queryFn: () => getExpenseSummary(month),
    staleTime: OLTP_STALE,
  })
}
export function useAddExpense() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ExpenseCreate) => addExpense(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['expense'] }),
  })
}

// 추천 (#32) — pantry seam 미배선이면 [] + note (degrade)
export function useMealRecommend(enabled = true) {
  return useQuery({
    queryKey: KEYS.mealRecommend,
    queryFn: () => recommendMeals(),
    staleTime: STALE.price,
    enabled,
  })
}

// 알림함 (#41~42)
export function useNotifications(unread = false) {
  return useQuery({
    queryKey: KEYS.notifications(unread),
    queryFn: () => listNotifications(unread),
    staleTime: OLTP_STALE,
  })
}
export function useMarkNotificationRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => markNotificationRead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
}
