// 이미지 파일 → 리사이즈된 JPEG data URI(#9). 별도 오브젝트 스토리지 없이
// user_recipe.image_url(text)에 그대로 저장·렌더하기 위해 클라이언트에서 축소·인코딩한다.
// 800px/quality 0.8 기준 대략 50~150KB — 저볼륨 유저 레시피엔 무해(추후 MinIO 이전 여지).
export async function fileToResizedDataUrl(file: File, maxDim = 800, quality = 0.8): Promise<string> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const fr = new FileReader()
    fr.onload = () => resolve(fr.result as string)
    fr.onerror = () => reject(new Error('파일을 읽지 못했어요'))
    fr.readAsDataURL(file)
  })
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const im = new Image()
    im.onload = () => resolve(im)
    im.onerror = () => reject(new Error('이미지를 열지 못했어요'))
    im.src = dataUrl
  })
  const scale = Math.min(1, maxDim / Math.max(image.width, image.height))
  const w = Math.max(1, Math.round(image.width * scale))
  const h = Math.max(1, Math.round(image.height * scale))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return dataUrl // 폴백: 원본 data URI
  ctx.drawImage(image, 0, 0, w, h)
  return canvas.toDataURL('image/jpeg', quality)
}
