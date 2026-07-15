import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 데이터 티어 서비스는 로컬에서 각기 다른 포트로 뜬다(게이트웨이 대체).
// 프론트는 항상 /api/* 상대경로로 호출하고, dev 프록시가 서비스로 라우팅한다.
// (운영: API Gateway가 동일하게 /api/* → 각 서비스로 라우팅 → 프론트 코드 불변)
const RECIPE = process.env.VITE_RECIPE_ORIGIN || 'http://localhost:8001'
const PRICE = process.env.VITE_PRICE_ORIGIN || 'http://localhost:8002'
const CHAT = process.env.VITE_CHAT_ORIGIN || 'http://localhost:8003'
const PANTRY = process.env.VITE_PANTRY_ORIGIN || 'http://localhost:8004' // services/pantry (#11~15)
// ⚠️ account 는 Dockerfile상 8003 = chat 과 충돌(포트/compose SoT 미정, CONVENTIONS §5). 로컬 병행 시 env 로 분리.
const ACCOUNT = process.env.VITE_ACCOUNT_ORIGIN || 'http://localhost:8003' // services/account (#2~10)

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api/recipes': { target: RECIPE, changeOrigin: true },
      '/api/prices': { target: PRICE, changeOrigin: true },
      '/api/mealplan/assistant': { target: CHAT, changeOrigin: true },
      '/api/pantry': { target: PANTRY, changeOrigin: true },
      '/api/auth': { target: ACCOUNT, changeOrigin: true },
      '/api/users': { target: ACCOUNT, changeOrigin: true },
    },
  },
})
