import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDeleteMe, useLogout, useMe, useUpdateMe } from '../../lib/queries'

// 계정 관리 — 닉네임 수정(#8)·로그아웃·회원 탈퇴(DELETE /me).
export default function AccountPanel({ onClose }: { onClose: () => void }) {
  const nav = useNavigate()
  const { data: me } = useMe()
  const update = useUpdateMe()
  const del = useDeleteMe()
  const logout = useLogout()
  const [nick, setNick] = useState('')
  const [confirmDel, setConfirmDel] = useState(false)

  const current = me?.nickname ?? ''
  const value = nick || current
  const canSave = value.trim().length >= 1 && value.trim() !== current

  const save = () => {
    if (!canSave) return
    update.mutate(value.trim(), { onSuccess: () => setNick('') })
  }
  const doLogout = async () => { await logout(); onClose(); nav('/login') }
  const doDelete = () => del.mutate(undefined, { onSuccess: () => { onClose(); nav('/login') } })

  return (
    <div>
      {/* 프로필 */}
      <div style={{ fontSize: 12, color: '#9A9A9A' }}>{me?.email ?? '이메일 없음'} · {me?.provider === 'kakao' ? '카카오' : '이메일'} 로그인</div>

      {/* 닉네임 수정 */}
      <div style={{ marginTop: 16 }}>
        <label style={{ fontSize: 13, fontWeight: 700, color: '#17264A' }}>닉네임</label>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <input
            value={value}
            onChange={(e) => setNick(e.target.value)}
            maxLength={30}
            style={{ flex: 1, padding: '11px 13px', border: '1.5px solid #E6E6E6', fontSize: 14, outline: 'none', minWidth: 0 }}
          />
          <button onClick={save} disabled={!canSave || update.isPending}
            style={{ padding: '0 18px', border: 'none', background: canSave ? '#F26419' : '#E6E6E6', color: '#fff', fontSize: 13.5, fontWeight: 700, cursor: canSave ? 'pointer' : 'not-allowed', whiteSpace: 'nowrap' }}>
            {update.isPending ? '저장 중…' : '저장'}
          </button>
        </div>
        {update.isSuccess && !nick && <div style={{ fontSize: 12, color: '#1B7A46', marginTop: 6 }}>닉네임을 변경했어요.</div>}
      </div>

      {/* 로그아웃 */}
      <button onClick={doLogout} style={{ width: '100%', marginTop: 22, padding: 13, border: '1.5px solid #E6E6E6', background: '#fff', color: '#17264A', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>로그아웃</button>

      {/* 회원 탈퇴 */}
      <div style={{ marginTop: 12, paddingTop: 14, borderTop: '1px solid #EFEFEF' }}>
        {!confirmDel ? (
          <button onClick={() => setConfirmDel(true)} style={{ width: '100%', padding: 12, border: 'none', background: 'transparent', color: '#F04452', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>회원 탈퇴</button>
        ) : (
          <div style={{ background: '#FDECEC', padding: 14 }}>
            <div style={{ fontSize: 13, color: '#F04452', fontWeight: 700, marginBottom: 4 }}>정말 탈퇴할까요?</div>
            <div style={{ fontSize: 12, color: '#B4434E', lineHeight: 1.5, marginBottom: 12 }}>예산·제외 재료 등 계정 데이터가 삭제되고 되돌릴 수 없어요.</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => setConfirmDel(false)} style={{ flex: 1, padding: 10, border: '1.5px solid #E6E6E6', background: '#fff', color: '#5E5E5E', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>취소</button>
              <button onClick={doDelete} disabled={del.isPending} style={{ flex: 1, padding: 10, border: 'none', background: '#F04452', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>{del.isPending ? '처리 중…' : '탈퇴하기'}</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
