import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 데이터 티어 서비스는 로컬에서 각기 다른 포트로 뜬다(게이트웨이 대체).
// 프론트는 항상 /api/* 상대경로로 호출하고, dev 프록시가 서비스로 라우팅한다.
// (운영: API Gateway가 동일하게 /api/* → 각 서비스로 라우팅 → 프론트 코드 불변)
// 포트 SoT(확정, CONVENTIONS §5): 서비스별 고정·무충돌. 각 서비스 Dockerfile --port 와 일치.
const RECIPE = process.env.VITE_RECIPE_ORIGIN || 'http://localhost:8001'
const PRICE = process.env.VITE_PRICE_ORIGIN || 'http://localhost:8002'
const CHAT = process.env.VITE_CHAT_ORIGIN || 'http://localhost:8003'
const ACCOUNT = process.env.VITE_ACCOUNT_ORIGIN || 'http://localhost:8004'
const PANTRY = process.env.VITE_PANTRY_ORIGIN || 'http://localhost:8005'
const RECIPEBOOK = process.env.VITE_RECIPEBOOK_ORIGIN || 'http://localhost:8006'
const MEALPLAN = process.env.VITE_MEALPLAN_ORIGIN || 'http://localhost:8007'
const NOTIFY = process.env.VITE_NOTIFY_ORIGIN || 'http://localhost:8008'
const OCR = process.env.VITE_OCR_ORIGIN || 'http://localhost:8010'   // OCR 엔진(독립, 포트 SoT 밖 8010)

// ⚠️ 프록시는 prefix 매칭 + 삽입 순서 우선 → 더 구체적인 경로를 반드시 먼저 둔다.
//    /api/recipes/book → recipebook (/api/recipes 보다 앞), /api/mealplan/assistant → chat (/api/mealplan 보다 앞).
// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api/recipes/book': { target: RECIPEBOOK, changeOrigin: true }, // ← /api/recipes 보다 먼저
      '/api/recipes/mine': { target: RECIPEBOOK, changeOrigin: true }, // 내 레시피(수동 등록)
      '/api/recipes/shared': { target: RECIPEBOOK, changeOrigin: true }, // 공개 공유 뷰
      '/api/recipes': { target: RECIPE, changeOrigin: true },
      '/api/mealplan/assistant': { target: CHAT, changeOrigin: true }, // ← /api/mealplan 보다 먼저
      '/api/mealplan': { target: MEALPLAN, changeOrigin: true },
      '/api/expenses': { target: MEALPLAN, changeOrigin: true },
      '/api/notifications': { target: NOTIFY, changeOrigin: true },
      '/api/pantry/ocr': { target: OCR, changeOrigin: true }, // ← OCR 엔진(업로드/폴링). /api/pantry 보다 먼저(확정=/api/pantry/receipts 는 pantry)
      '/api/pantry': { target: PANTRY, changeOrigin: true },
      '/api/auth': { target: ACCOUNT, changeOrigin: true },
      '/api/users': { target: ACCOUNT, changeOrigin: true },
      '/api/prices': { target: PRICE, changeOrigin: true },
    },
  },
})
