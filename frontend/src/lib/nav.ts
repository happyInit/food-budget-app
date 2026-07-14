import { Home, BookOpen, Refrigerator, Wallet, User } from 'lucide-react'

// 하단탭(모바일) / 사이드바(데스크톱) 공용 네비 설정
export const NAV = [
  { to: '/home', label: '홈', Icon: Home },
  { to: '/recipes', label: '레시피', Icon: BookOpen },
  { to: '/fridge', label: '냉장고', Icon: Refrigerator },
  { to: '/expense', label: '식비', Icon: Wallet },
  { to: '/my', label: '마이', Icon: User },
] as const
