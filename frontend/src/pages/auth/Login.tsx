import { useNavigate } from 'react-router-dom'
import AuthLayout, { Field, inputCls } from './AuthLayout'
import { Button } from '../../components/ui'

export default function Login() {
  const nav = useNavigate()
  return (
    <AuthLayout title="이메일 로그인" sub="가입한 이메일과 비밀번호를 입력하세요.">
      <div className="mb-4 rounded-lg bg-danger-weak px-3 py-2.5 text-xs font-semibold text-danger">
        비밀번호가 일치하지 않아요. 다시 확인해 주세요.
      </div>
      <Field label="이메일">
        <input className={inputCls} defaultValue="bravo@meal.kr" />
      </Field>
      <Field label="비밀번호">
        <input className={inputCls} type="password" defaultValue="password" />
      </Field>
      <Button size="lg" className="mt-1 w-full" onClick={() => nav('/home')}>
        로그인
      </Button>
      <p className="mt-5 text-center text-sm text-sub">
        <button onClick={() => nav('/signup')} className="font-bold text-brand">
          회원가입
        </button>{' '}
        · <button className="font-bold text-brand">비밀번호 찾기</button>
      </p>
    </AuthLayout>
  )
}
