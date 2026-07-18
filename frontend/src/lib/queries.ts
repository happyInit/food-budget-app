// 데이터 페칭 = React Query 단일화. 캐시 키·staleTime을 여기서 일괄 관리.
// 원칙: 정적(레시피)=길게 · mutable(가격·OLTP)=짧게. 상세는 클릭 진입 시 fetch(자동 캐시).
import { useCallback } from 'react'
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addBookmark, addCartItem, addExcludedItem, addExpense, addPantryItem, checkoutCart, deleteCartItem,
  deleteMe, deletePantryItem, getBudget, getCalendar, getCart, getExcludedItems, getExpenseBreakdown,
  getExpenseSummary, getExpiring, getHotdeals, getMe, getPantryItems, getPantryStats, getRecipe, getRecommend,
  getToken, listBookmarks, listNotifications, login, logout, markNotificationRead, patchPantryItem, putBudget,
  recommendMeals, removeBookmark, removeExcludedItem, searchItems, searchRecipes, setToken, setRefreshToken,
  clearSession, signup, updateMe,
  createMyRecipe, deleteMyRecipe, getMyRecipe, getSharedRecipe, listMyRecipes, shareMyRecipe, unshareMyRecipe,
  publishMyRecipe, unpublishMyRecipe, listSharedRecipes,
  submitOcr, getOcrJob, confirmReceipt,
} from './api'
import type { CartItemCreate, ExpenseCreate, ReceiptConfirm, SignupBody, UserRecipeCreateBody } from './api'
import type { PantryAddBody, PantryPatchBody } from './types'

// 데이터 성격별 신선도(ms)
export const STALE = {
  recipe: 30 * 60 * 1000, // 레시피(크롤링 정적) — 30분
  price: 2 * 60 * 1000, // 가격·추천·핫딜(자주 변함) — 2분
  pantry: 60 * 1000, // 재고(유저 mutable) — 뮤테이션 시 무효화, staleTime은 짧게
  user: 5 * 60 * 1000, // 프로필·예산(가끔 변함)
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

// 레시피 상세 — 클릭 진입 시 fetch, 재방문 시 캐시 즉시(30분).
export function useRecipe(id: number) {
  return useQuery({
    queryKey: ['recipe', id],
    queryFn: () => getRecipe(id),
    staleTime: STALE.recipe,
    enabled: Number.isFinite(id),
  })
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

// 내 레시피 (#24 수동 등록 + 공유)
const MY_RECIPES_KEY = ['myRecipes'] as const
export function useMyRecipes() {
  return useQuery({ queryKey: MY_RECIPES_KEY, queryFn: listMyRecipes, staleTime: OLTP_STALE })
}
export function useMyRecipe(id: number) {
  return useQuery({
    queryKey: ['myRecipe', id],
    queryFn: () => getMyRecipe(id),
    enabled: Number.isFinite(id) && id > 0,
    staleTime: OLTP_STALE,
  })
}
export function useCreateMyRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: UserRecipeCreateBody) => createMyRecipe(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: MY_RECIPES_KEY }),
  })
}
export function useDeleteMyRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deleteMyRecipe(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: MY_RECIPES_KEY }),
  })
}
export function useShareMyRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => shareMyRecipe(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: MY_RECIPES_KEY }),
  })
}
export function useUnshareMyRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => unshareMyRecipe(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: MY_RECIPES_KEY }),
  })
}
// 발행(공개 카탈로그) — 내 레시피를 레시피 목록에 공개/취소. 목록 갱신 + 발행 리스트 무효화.
export function usePublishMyRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => publishMyRecipe(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: MY_RECIPES_KEY })
      qc.invalidateQueries({ queryKey: ['myRecipe'] }) // 상세뷰 공개상태·토큰 갱신
      qc.invalidateQueries({ queryKey: ['sharedRecipes'] })
    },
  })
}
export function useUnpublishMyRecipe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => unpublishMyRecipe(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: MY_RECIPES_KEY })
      qc.invalidateQueries({ queryKey: ['myRecipe'] })
      qc.invalidateQueries({ queryKey: ['sharedRecipes'] })
    },
  })
}
// 공개 발행 레시피 목록/검색(비인증) — 레시피 검색에서 카탈로그와 합쳐 노출.
export function useSharedRecipes(q: string) {
  return useQuery({
    queryKey: ['sharedRecipes', q],
    queryFn: () => listSharedRecipes(q),
    staleTime: STALE.recipe,
  })
}
// 공개 공유 뷰(비인증) — 로그인 없이 링크 토큰으로 조회
export function useSharedRecipe(token: string) {
  return useQuery({
    queryKey: ['sharedRecipe', token],
    queryFn: () => getSharedRecipe(token),
    enabled: !!token,
    staleTime: STALE.recipe,
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

// 성과보기 '식비 구성' — 카테고리 구성. ['expense'] 접두어 → 지출 기록·checkout 시 자동 무효화.
export function useExpenseBreakdown(month: string) {
  return useQuery({
    queryKey: ['expense', 'breakdown', month],
    queryFn: () => getExpenseBreakdown(month),
    staleTime: OLTP_STALE,
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

// 성과보기 '안 버린 재료·폐기'. ['pantry'] 접두어 → 재고 소비/폐기(PATCH status) 시 자동 무효화.
export function usePantryStats(month?: string) {
  return useQuery({
    queryKey: ['pantry', 'stats', month ?? 'all'],
    queryFn: () => getPantryStats(month),
    staleTime: STALE.pantry,
  })
}

// 재고가 바뀌면 재고 기반 추천(#32)도 다시 계산해야 함 → mealRecommend 도 함께 무효화.
function invalidatePantryAndDerived(qc: ReturnType<typeof useQueryClient>, alsoExpense = false) {
  qc.invalidateQueries({ queryKey: PANTRY_KEY }) // 목록·임박·통계
  qc.invalidateQueries({ queryKey: KEYS.mealRecommend }) // 뭐 해먹지 추천 재계산
  if (alsoExpense) qc.invalidateQueries({ queryKey: ['expense'] }) // 소비/폐기 → 요약 saved_ingredients
}

export function useAddPantryItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: PantryAddBody) => addPantryItem(body),
    onSuccess: () => invalidatePantryAndDerived(qc),
  })
}

// 여러 재료를 한 번에 냉장고에 등록 (장바구니 구매완료 → 냉장고 담기). 병렬 POST 후 1회 무효화.
export function useAddPantryItems() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (bodies: PantryAddBody[]) => Promise.all(bodies.map(addPantryItem)),
    onSuccess: () => invalidatePantryAndDerived(qc),
  })
}

export function usePatchPantryItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: PantryPatchBody }) => patchPantryItem(id, patch),
    onSuccess: () => invalidatePantryAndDerived(qc, true), // status 전이 → 성과지표도 갱신
  })
}

export function useDeletePantryItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deletePantryItem(id),
    onSuccess: () => invalidatePantryAndDerived(qc),
  })
}

// ── OCR 영수증 (업로드=엔진 · 폴링 · 확정=pantry + 식비=mealplan) ──
export function useSubmitOcr() {
  return useMutation({ mutationFn: (file: File) => submitOcr(file) })
}

// job 폴링 — PENDING 동안 1s 간격, DONE/FAILED 면 중단.
export function useOcrJob(jobId: string | null) {
  return useQuery({
    queryKey: ['ocr', 'job', jobId],
    queryFn: () => getOcrJob(jobId as string),
    enabled: !!jobId,
    staleTime: 0,
    refetchInterval: (q) => (q.state.data?.status === 'PENDING' ? 1000 : false),
  })
}

// 확정 → pantry 저장 + 식비 기록(mealplan). 두 서비스 순차 호출(프론트 오케스트레이션, 순환의존 회피).
// pantry 저장 성공 후 식비 기록이 실패해도 재고는 유지 → expenseRecorded=false 로 알림(전체 실패 아님).
export function useConfirmReceipt() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: ReceiptConfirm) => {
      const res = await confirmReceipt(body)
      let expenseRecorded = false
      if (res.expense_amount > 0) {
        try {
          const spent_on = (body.purchased_at ?? '').slice(0, 10) || new Date().toISOString().slice(0, 10)
          await addExpense({
            amount: res.expense_amount, category: 'GROCERY', spent_on,
            source: 'OCR', memo: body.store ?? '영수증 OCR',
          })
          expenseRecorded = true
        } catch {
          /* pantry는 이미 저장됨 — 식비 기록만 실패. 컴포넌트가 안내. */
        }
      }
      return { ...res, expenseRecorded }
    },
    onSuccess: () => invalidatePantryAndDerived(qc, true), // pantry 목록·임박·통계 + 식비 캘린더/요약
  })
}

// ── Account (#2 signup / #3 login / #7 me / #9·#10 budget / logout) ──
// 유저 조회는 토큰이 있을 때만(enabled). 로그인 성공 시 setToken + 전체 무효화로 유저-스코프 재조회.
export function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: getMe, staleTime: STALE.user, enabled: !!getToken() })
}

export function useBudget() {
  return useQuery({ queryKey: ['budget'], queryFn: getBudget, staleTime: STALE.user, enabled: !!getToken() })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) => login(email, password),
    onSuccess: (data) => {
      setToken(data.access_token) // 이후 '인증 O' API에 자동 첨부
      setRefreshToken(data.refresh_token) // access(30분) 만료 시 silent 재발급용
      qc.invalidateQueries() // me·budget·pantry 등 유저-스코프 전부 재조회
    },
  })
}

export function useSignup() {
  return useMutation({ mutationFn: (body: SignupBody) => signup(body) })
}

// 닉네임 수정 (#8) — 성공 시 me 재조회.
export function useUpdateMe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (nickname: string) => updateMe(nickname),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['me'] }),
  })
}

// 회원 탈퇴 — 성공 시 토큰 삭제 + 캐시 비우기(로그인 화면으로).
export function useDeleteMe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => deleteMe(),
    onSuccess: () => { clearSession(); qc.clear() },
  })
}

// ── 제외(회피) 재료 — 변경 시 추천(mealRecommend)도 재계산 ──
export function useExcludedItems() {
  return useQuery({ queryKey: ['excludedItems'], queryFn: getExcludedItems, staleTime: STALE.user, enabled: !!getToken() })
}

export function useItemSearch(q: string) {
  return useQuery({
    queryKey: ['itemSearch', q],
    queryFn: () => searchItems(q),
    enabled: q.trim().length >= 1,
    staleTime: STALE.recipe,
  })
}

export function useAddExcludedItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ item_id, name }: { item_id: number; name: string }) => addExcludedItem(item_id, name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['excludedItems'] })
      qc.invalidateQueries({ queryKey: KEYS.mealRecommend })
    },
  })
}

export function useRemoveExcludedItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (item_id: number) => removeExcludedItem(item_id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['excludedItems'] })
      qc.invalidateQueries({ queryKey: KEYS.mealRecommend })
    },
  })
}

export function usePutBudget() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (amount: number) => putBudget(amount),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['budget'] })
      // 홈·식비·장바구니·성과·마이는 예산을 expense summary(['expense',…])로 읽음 → 함께 무효화해야 새로고침 없이 즉시 반영.
      qc.invalidateQueries({ queryKey: ['expense'] })
    },
  })
}

// 로그아웃 = 서버 best-effort 호출 후 토큰 삭제 + 캐시 비우기(스테이트리스 JWT).
// useCallback으로 identity 안정화 — useIdleLogout 등이 effect deps로 안전하게 의존.
export function useLogout() {
  const qc = useQueryClient()
  return useCallback(async () => {
    try {
      await logout()
    } catch {
      /* 스테이트리스 — 서버 실패해도 클라 토큰만 지우면 됨 */
    }
    clearSession()
    qc.clear()
  }, [qc])
}
