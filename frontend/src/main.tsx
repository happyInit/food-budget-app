import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'
import { ExtractionProvider } from './lib/extraction'

// 전역 캐시 기본값 — 상세 staleTime은 쿼리별로 재지정(lib/queries.ts)
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 기본 5분간 fresh(재요청 안 함)
      gcTime: 30 * 60 * 1000, // 미사용 캐시 30분 보관
      retry: 1,
      refetchOnWindowFocus: false, // 탭 포커스마다 재요청 안 함
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ExtractionProvider>
          <App />
        </ExtractionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
