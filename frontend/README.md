# 밀플래닝 — Frontend

React + Vite + TypeScript + PWA 웹앱. (스택 정본: `docs/design.md` §6.1)

## 개발 기준 문서 (`references/`)
| 파일 | 용도 |
|---|---|
| `프론트엔드 화면정의서.pdf` | **최종 화면 시안 (정본)** |
| `화면정의서.xlsx` | 화면목록·공통UI·사용자흐름 (SCR-001~022) — *SSOT는 `docs/design/frontend specification.xlsx`* |
| `밀플래닝 확정본.html` | 렌더 시안 (25MB, **git 제외 — 로컬만**) |

## 에셋 (`public/icons/`)
- `app-icon.png` — **앱 메인 아이콘 + 챗봇(대화형 어시스턴트) 아이콘** 공용

## 화면 (SCR-001~022)
인증(001–004) · 홈(005) · 냉장고/OCR(006–009) · 레시피(010–011) · 밀플래닝(012) · 장바구니(013) · 식비(014–016) · 알림/마이/레시피북(017–019) · YouTube추출(020) · 핫딜(021) · 어시스턴트(022)

## 스택
- **React + Vite + TypeScript**
- **PWA** (홈화면 설치 + 최저가·유통기한 임박 푸시알림)
- **TanStack Query** (서버 데이터 캐시·갱신), **Zustand** (클라 상태)
- **Tailwind** (스타일)

## 백엔드 연동
- API 명세: `docs/design/api-spec.md` (~46 엔드포인트, Auth 분리 반영)
- Gateway → Auth/User/Pantry/Recipe/Price/MealPlan/ML Serving

## 시작
```bash
# (초기 셋업 예정)
npm create vite@latest . -- --template react-ts
npm i @tanstack/react-query zustand tailwindcss
```
