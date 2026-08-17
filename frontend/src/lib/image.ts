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

// ── 영수증 업로드용 축소 ─────────────────────────────────────────────────────
// 🔴 **왜 클라이언트에서 줄이나** — 서버가 어차피 줄이는데.
//    OCR 이 Lambda 로 가면 **ALB → Lambda 요청 본문 상한이 1 MB** 다(AWS 고정, 올릴 수 없다).
//    휴대폰 영수증 사진은 통상 2~5MB 라 **함수에 닿지도 못한다.** 결정·근거 =
//    `docs/serverless/07_G-06_영수증_이미지_전달경로_결정.md`.
//
// 🔵 **품질을 잃지 않는다.** 서버(`services/ocr/.../vision.py`)가 이미 최장변 1600px·JPEG q85 로
//    줄여서 모델에 넘긴다. 여기서 같은 크기로 줄이면 모델이 보는 그림은 **오늘과 똑같다.**
//    ⇒ 품질 트레이드오프가 아니라 «같은 일을 더 일찍» 하는 것이다. 그래서 아래 값은
//       서버의 `image_max_side`·quality 와 **같은 숫자여야 한다** — 갈리면 한쪽이 두 번 줄인다.
//
// 🔵 그래서 **지금 넣어도 동작이 안 바뀐다.** 파드가 받아도 `max(size) <= 1600` 이라 그대로 통과한다.
//    Lambda 이관과 분리해서 먼저 넣을 수 있는 이유가 이것이다.
const RECEIPT_MAX_DIM = 1600
const RECEIPT_QUALITY = 0.85

/** 순수 계산 — `max` 안에 들어가게 줄인 크기. 이미 작으면 `null`(= 건드리지 않는다). */
export function fitWithin(w: number, h: number, max = RECEIPT_MAX_DIM): { w: number; h: number } | null {
  if (!(w > 0) || !(h > 0)) return null // 0·NaN — 판단 불가라 원본을 그대로 둔다
  const longest = Math.max(w, h)
  if (longest <= max) return null // 🔵 이미 작다 → 재인코딩하지 않는다(불필요한 손실 세대를 안 만든다)
  const scale = max / longest
  return { w: Math.max(1, Math.round(w * scale)), h: Math.max(1, Math.round(h * scale)) }
}

/**
 * 영수증 사진을 업로드 크기로 줄인다. **실패하면 원본을 그대로 돌려준다** — 축소는 최적화지
 * 요구사항이 아니라서, 여기서 던지면 «사진을 못 올리는» 회귀가 된다.
 *
 * 🔴 **EXIF 회전을 픽셀에 굽는다.** `createImageBitmap(…, {imageOrientation:'from-image'})` 가
 *    그 일을 한다. 이게 없으면 세로로 찍은 사진이 **눕혀서** 모델에 들어가고, 그건
 *    아무 에러 없이 인식률만 떨어뜨린다.
 *    ⚠️ 현재 서버는 EXIF 를 **전혀 처리하지 않는다**(`services/ocr/` 에 `exif_transpose` 0건).
 *       1600px 초과 사진은 재인코딩되며 회전 태그가 통째로 사라지므로, 지금도 눕은 채로
 *       들어가고 있을 수 있다. 여기서 구워 보내면 **개선**이다.
 *    ⚠️ 구형 브라우저는 `imageOrientation` 을 무시한다 — 그때는 축소만 되고 회전은 그대로다.
 *       더 나빠지지는 않는다(지금과 같다).
 */
export async function shrinkReceipt(file: File, maxDim = RECEIPT_MAX_DIM): Promise<File> {
  try {
    if (typeof createImageBitmap !== 'function' || typeof document === 'undefined') return file
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
    try {
      const size = fitWithin(bitmap.width, bitmap.height, maxDim)
      if (!size) return file
      const canvas = document.createElement('canvas')
      canvas.width = size.w
      canvas.height = size.h
      const ctx = canvas.getContext('2d')
      if (!ctx) return file
      ctx.drawImage(bitmap, 0, 0, size.w, size.h)
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, 'image/jpeg', RECEIPT_QUALITY),
      )
      // 🔵 커졌으면 버린다 — 작은 PNG 를 JPEG 로 다시 굽다가 오히려 불어나는 경우가 있다.
      if (!blob || blob.size >= file.size) return file
      return new File([blob], file.name.replace(/\.[^.]+$/, '') + '.jpg', {
        type: 'image/jpeg',
        lastModified: file.lastModified,
      })
    } finally {
      bitmap.close?.()
    }
  } catch {
    return file // 열지 못했거나 캔버스가 없다 — 원본으로 간다(서버가 줄인다)
  }
}
