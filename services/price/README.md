# Price Service

현재가·이력·시세추천·핫딜 (데이터 티어 읽기). `docs/design/api-spec.md` #26·#27·#28·#31.

## 엔드포인트
| Method | Path | 설명 | 소스 |
|---|---|---|---|
| GET | `/health` | 헬스체크 | — |
| GET | `/api/prices/recommend?limit=` | 지금 싼 재료 (#28) | `retail_item_price_compare` 뷰 |
| GET | `/api/prices/hotdeals?limit=` | 오아시스 마감세일 등 (#31) | `retail_product`+`retail_price`(deal_type≠general) |
| GET | `/api/prices/{item_id}` | 현재가 — 소스별 최저 단가 + 통계 baseline (#26) | `retail_unit_price` 뷰 + `price_online_daily` |
| GET | `/api/prices/{item_id}/history?limit=` | 가격 이력 (#27) | `retail_price` 시계열 |

- `{item_id}` = `item_master.item_id` (품목 표준 ID).
- baseline(`price_online_daily`)은 데이터가 희소해 대부분 `null` — nullable.
- JWT 미검증 (Gateway/Auth 도입 시 추가).

## 로컬 실행
```bash
cp .env.example .env   # PGPASSWORD 채우기 (커밋 금지)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8002
# curl 'http://localhost:8002/api/prices/hotdeals?limit=5'
# curl 'http://localhost:8002/api/prices/recommend?limit=5'
# curl 'http://localhost:8002/api/prices/29'         # 양파
# curl 'http://localhost:8002/api/prices/29/history?limit=10'
```
