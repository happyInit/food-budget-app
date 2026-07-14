import { useNavigate } from 'react-router-dom'
import AuthLayout, { Field, inputCls } from './AuthLayout'
import { Button } from '../../components/ui'

export default function Signup() {
  const nav = useNavigate()
  return (
    <AuthLayout title="회원가입" sub="이메일 인증 후 계정을 만들어요.">
      <Field label="이메일">
        <div className="flex gap-2">
          <input className={inputCls} placeholder="you@email.com" />
          <Button variant="line" size="sm" className="shrink-0 whitespace-nowrap">
            인증요청
          </Button>
        </div>
      </Field>
      <Field label="인증번호">
        <div className="flex gap-2">
          <input className={inputCls} placeholder="6자리 숫자" />
          <Button variant="ghost" size="sm" className="shrink-0">
            확인
          </Button>
        </div>
      </Field>
      <Field label="비밀번호">
        <input className={inputCls} type="password" placeholder="8자 이상" />
      </Field>
      <label className="mb-5 mt-1 flex items-center gap-2.5 text-sm text-sub">
        <input type="checkbox" defaultChecked className="accent-brand" />
        (필수) 이용약관 · 개인정보 처리방침 동의
      </label>
      <Button size="lg" className="w-full" onClick={() => nav('/budget')}>
        가입하고 예산 설정
      </Button>
    </AuthLayout>
  )
}
