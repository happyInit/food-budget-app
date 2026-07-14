import { Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'
import AppShell from './components/layout/AppShell'
import Home from './pages/Home'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />

      {/* 앱 셸(반응형: 모바일 하단탭 / 데스크톱 사이드바) */}
      <Route element={<AppShell />}>
        <Route path="/home" element={<Home />} />
      </Route>
    </Routes>
  )
}
