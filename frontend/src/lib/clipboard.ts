// 링크 복사 — navigator.clipboard(보안 컨텍스트 https/localhost 필요)를 우선 쓰되,
// 부재/거부(비-secure dev, Safari 제스처 밖) 시 textarea+execCommand로 폴백. 성공 여부 반환.
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* 폴백으로 진행 */
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.top = '0'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
