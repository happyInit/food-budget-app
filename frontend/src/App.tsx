import { Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'
import Start from './pages/auth/Start'
import Login from './pages/auth/Login'
import Signup from './pages/auth/Signup'
import BudgetSetup from './pages/auth/BudgetSetup'
import AppShell from './components/layout/AppShell'
import Home from './pages/Home'
import Fridge from './pages/Fridge'

export default function App() {
  return (
    <Routes>
      {/* 랜딩 + 인증 (셸 없음) */}
      <Route path="/" element={<Landing />} />
      <Route path="/start" element={<Start />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/budget" element={<BudgetSetup />} />

      {/* 앱 셸 (반응형: 모바일 하단탭 / 데스크톱 사이드바) */}
      <Route element={<AppShell />}>
        <Route path="/home" element={<Home />} />
        <Route path="/fridge" element={<Fridge />} />
      </Route>
    </Routes>
  )
}
