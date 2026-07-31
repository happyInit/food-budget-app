import { Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'
import Login from './pages/auth/Login'
import EmailLogin from './pages/auth/EmailLogin'
import Signup from './pages/auth/Signup'
import BudgetSetup from './pages/auth/BudgetSetup'
import OAuthCallback from './pages/auth/OAuthCallback'
import AppShell from './components/layout/AppShell'
import Home from './pages/Home'
import Fridge from './pages/Fridge'
import FridgeAdd from './pages/FridgeAdd'
import RecipeSearch from './pages/RecipeSearch'
import RecipeDetail from './pages/RecipeDetail'
import MealPlan from './pages/MealPlan'
import Cart from './pages/Cart'
import Expense from './pages/Expense'
import ExpenseAdd from './pages/ExpenseAdd'
import Performance from './pages/Performance'
import Notifications from './pages/Notifications'
import My from './pages/My'
import Recipebook from './pages/Recipebook'
import MyRecipeDetail from './pages/MyRecipeDetail'
import YoutubeExtract from './pages/YoutubeExtract'
import Hotdeal from './pages/Hotdeal'
import Assistant from './pages/Assistant'
import SharedRecipe from './pages/SharedRecipe'
import SharedRecipeInApp from './pages/SharedRecipeInApp'

export default function App() {
  return (
    <Routes>
      {/* 랜딩 + 인증 (셸 없음) */}
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/login/email" element={<EmailLogin />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/budget" element={<BudgetSetup />} />
      <Route path="/auth/:provider/callback" element={<OAuthCallback />} />

      {/* 공개 공유 레시피 뷰 (로그인·셸 없음) */}
      <Route path="/shared/:token" element={<SharedRecipe />} />

      {/* 앱 셸 (반응형: 모바일 하단탭 / 데스크톱 사이드바) */}
      <Route element={<AppShell />}>
        <Route path="/home" element={<Home />} />

        {/* 냉장고 */}
        <Route path="/pantry" element={<Fridge />} />
        <Route path="/pantry/add" element={<FridgeAdd />} />

        {/* 레시피 · 밀플래닝 · 장바구니 */}
        <Route path="/recipes" element={<RecipeSearch />} />
        <Route path="/recipes/shared/:token" element={<SharedRecipeInApp />} />
        <Route path="/recipes/:id" element={<RecipeDetail />} />
        <Route path="/mealplan" element={<MealPlan />} />
        <Route path="/cart" element={<Cart />} />

        {/* 식비 */}
        <Route path="/expense" element={<Expense />} />
        <Route path="/expense/add" element={<ExpenseAdd />} />
        <Route path="/performance" element={<Performance />} />

        {/* 핫딜 · 어시스턴트 */}
        <Route path="/hotdeal" element={<Hotdeal />} />
        <Route path="/assistant" element={<Assistant />} />

        {/* 알림센터 · 마이 · 레시피북 · YouTube추출 */}
        <Route path="/notifications" element={<Notifications />} />
        <Route path="/my" element={<My />} />
        <Route path="/recipebook" element={<Recipebook />} />
        <Route path="/recipebook/:id" element={<MyRecipeDetail />} />
        <Route path="/youtube" element={<YoutubeExtract />} />
      </Route>
    </Routes>
  )
}
