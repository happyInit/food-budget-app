import { useNavigate } from 'react-router-dom'
import AuthLayout from './AuthLayout'
import { Button } from '../../components/ui'

export default function Start() {
  const nav = useNavigate()
  return (
    <AuthLayout title="밀플래닝 시작하기" sub="카카오 또는 이메일로 3초 만에 시작하세요.">
      <button className="flex w-full items-center justify-center gap-2 rounded-xl bg-[#FEE500] py-3.5 text-[15px] font-extrabold text-[#191600]">
        💬 카카오로 시작
      </button>
      <div className="my-5 flex items-center gap-3 text-xs text-faint">
        <div className="h-px flex-1 bg-line" />
        또는
        <div className="h-px flex-1 bg-line" />
      </div>
      <Button variant="line" size="lg" className="mb-2.5 w-full" onClick={() => nav('/login')}>
        이메일로 로그인
      </Button>
      <Button variant="ghost" size="lg" className="w-full" onClick={() => nav('/signup')}>
        이메일로 회원가입
      </Button>
      <p className="mt-6 text-center text-sm text-sub">
        먼저 둘러볼래요?{' '}
        <button onClick={() => nav('/home')} className="font-bold text-brand">
          체험하기 →
        </button>
      </p>
    </AuthLayout>
  )
}
