# 오아시스마켓 식자재 크롤러

월 식비 예산 앱(food-budget-app)의 **가격·상품 메타 수집기**. 오아시스마켓에서 식자재 상품을
현재 판매가 + 신선도/원산지/용량과 함께 긁어 **JSONL**로 떨군다.

- 코드: [`oasis_crawler.py`](oasis_crawler.py)
- 샘플 출력: [`sample_output.jsonl`](sample_output.jsonl) (8건, 채소·정육·반찬·냉동)
- 설계 정본 연동: `docs/design.md` §3(데이터소스) · §4(AI) · §6.3(표준 품목 마스터)

> ⚠️ design.md(SSOT)는 아직 가격소스=마켓컬리로 기재. 오아시스 채택·필드 확정은 **팀 반영 대기**.
> 이 크롤러/스키마는 §8.2 마켓컬리 실측 컬럼 분석과 **일관**되게 설계됨(리테일러-무관 스키마, `source`로 구분).

---

## 1. 어떻게 크롤링하나 — 2단계

오아시스는 **anti-bot 없음 + 서버사이드 렌더링**이라 우회 기술 불필요. 두 경로를 조합한다.

```
① discovery : GET /api/product/list?categoryId={cat}&rows=200   (내부 JSON API)
                → [{"productId":34553,"productTitle":"…", …scores}]   ※ 가격 없음, ID 목록만
② record    : GET /product/detail/{productId}                    (서버렌더 HTML)
                → og:title/price + 상품정보 박스 + 상품정보제공고시 테이블 파싱
출력        : JSONL (줄당 상품 1개)
```

**왜 2단계인가**
- `/api/product/list`는 **랭킹/스코어 API** — productId·제목·정렬점수만 주고 **가격이 없다.** 그래서 discovery(ID 확보)에만 씀.
- 가격·용량·원산지·보관·소비기한은 전부 **상세페이지 HTML**에 있음 → 상품별 detail 요청으로 채운다.
- detail JSON API(`/api/product/detail/*` 등)는 전부 404 — 존재하지 않음(정찰 확인).

**파싱 시 함정 (코드에 반영됨)**
- 💥 **단가 함정**: 페이지에 연관상품 단가(`100g당 …원`)가 여러 개 → 반드시 `div.price` / 상품정보 '용량' 스코프 안에서만.
- 💥 **고시 라벨 상품군마다 다름**: 채소=`용량/수량/크기`·`원산지`, 버섯=`상품구성`·`생산자 및 소재지`(원산지가 소재지 값에 임베드), 육류=`중량`.
  → 공백정규화 + 라벨 변형 순서 조회 + 셀 페어와이즈 파싱 + 소재지→원산지 추출로 흡수.

---

## 2. 어떤 데이터를 뽑나 — 필드 스키마

가격 정책(팀 확정): **`price`(판매가)만.** 정상가·할인율·쿠폰최대혜택가 **미수집**(사람마다 쿠폰 달라 "실제 낸 값"만 의미).

| 필드 | 타입 | 소스 위치(HTML) | 소비처 |
|---|---|---|---|
| `source` | `"oasis"` | (상수) | 멀티리테일러 구분(마컬 병행 대비) |
| `product_id` | str | `og:url` 복합형 `{cat}-{prod}` | PK·가격이력 조인 키 |
| `url` / `image_url` | str | `og:url` / `og:image` | 링크·ES 카드 |
| `name` | str | `og:title` | **CRF NER → item_code**, ES nori |
| `category_id` | int | discovery 컨텍스트 | 분류·랭킹 |
| `deal_type` | `general`\|`closeSale` | 수집 경로 | 핫딜 추천 |
| `crawled_at` | ISO8601 KST | 수집시각 | **가격 이력 타임스탬프**(이상탐지) |
| **`price`** | int(원) | `div.price .textPrice b` | ★ **구매가격**. 최저가 이상탐지·예산 |
| `timedeal_end` | epoch ms\|null | `div.price [data-end-time]` | 핫딜 마감 타이머 |
| `volume_text` | str\|null | 고시 `용량/수량/크기`·`상품구성`·`중량` | 원문 보존 |
| `weight_g` | int\|null | ← volume_text 파싱(kg·g·ml 환산) | 소요량 계산 |
| **`unit_price`** | int\|null | 상품정보 `용량: 100g당 N원` | ★ **가성비 최저가 비교**(팩크기 무관) |
| `unit_basis` | str\|null | ← 위 (`"100g"`, `"1개"` …) | 단가 기준 |
| **`storage`** | str\|null | 상품정보 `보관방법`(신선/냉장/냉동/실온) | **신선도 XGBoost·냉동/냉장 분류** |
| `expiry_text` | str\|null | 고시 `소비기한`(폴백 품질유지기한) | 신선도 prior (raw) |
| `origin` | str\|null | 고시 `원산지`(폴백 소재지 추출) | 품목마스터·표시 |
| `is_fresh_seasonal` | bool | `og:title` '햇상품' | 추천 신호(name 기반 best-effort) |
| `delivery_types` | list | 상품정보 `배송구분` | 배송옵션 |
| `is_sold_out` | bool | 품절 버튼/클래스(best-effort) | 재고 |

**전처리로 미룬 파생값**(크롤=raw 원칙): `shelf_life_days`(예: `"제조일로부터 냉장 5일"`→5), `effective 100g 단가 통일`(basis가 `1개`인 경우 weight로 환산), `expiry_text` 정형화, SKU→표준 품목코드 매핑(§6.3 NER).

---

## 3. 사용법

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# [일반] 카테고리 여러 개, 카테고리당 최대 3건, 파일로
python oasis_crawler.py --categories 11,216,247 --limit 3 --out out.jsonl

# [일반] 전량(카테고리 내 전 상품), stdout으로, 요청 간격 2초
python oasis_crawler.py --categories 11 --interval 2 > veg.jsonl

# [딜] 마감세일 — 매일 17시 오픈. 17시 이후 실행해야 결과 나옴(deal_type=closeSale)
python oasis_crawler.py --deal closeSale --out closesale.jsonl

# [딜] 타임세일
python oasis_crawler.py --deal timeSale --out timesale.jsonl
```

| 옵션 | 설명 |
|---|---|
| `--categories` | 카테고리ID 콤마구분 (예: `11,216`). `--deal`과 택일 |
| `--deal` | `closeSale`(마감세일·17시 오픈) / `timeSale`(타임세일). `--categories`와 택일 |
| `--limit` | 소스당 최대 상품 수 (기본 전량) |
| `--out` | 출력 JSONL 경로 (기본 stdout `-`) |
| `--interval` | 요청 간 최소 간격 초 (기본 1.5) |

### 주요 식자재 카테고리ID
`11` 친환경채소 · `142` 채소 · `141` 과일│농산 · `12` 수입과일농산 · `49` 버섯│건나물 ·
`9` 쌀│잡곡 · `13` 견과│선식 · `3` 축산 · `216` 축산│유제품 · `1274` 수산 · `1275` 축산 ·
`246` 국│반찬 · `247` 간편식 · `219` 빵│잼 · `1191` 양념│면 · `123` 오아시스반찬 · `120` 밀키트│도시락
*(전체 목록은 `/product/closeSale` 등 페이지 네비게이션의 `categoryId=` 링크로 확보)*

---

## 4. 크롤 정책 (하드 — 준수 필수)

- **교육용·비상업·비공개** 전제. 상업 서비스 아님.
- **anti-bot 우회 없음** (오아시스는 anti-bot 부재 → 우회 자체가 불필요).
- **rate-limit**: 요청 간 최소 `--interval`초(기본 1.5) + 백오프. 서버 부담 X.
- honest User-Agent(연락처 포함). robots.txt 부재 ≠ 허용 → ToS 회색지대이므로 넉넉한 간격·소량.
- **가격·상품 메타만.** 개인정보·리뷰 수집 안 함.

---

## 5. 알려진 한계 · 다음 작업

1. **핫딜(closeSale/timeSale) — 해결됨(구현), 단 시간 게이트**: `/product/closeSale` 페이지 자체는 JS 렌더라 비어 보이지만, 실제로는 **list API 필터**(`?closeSaleYn=Y` / `?timeSaleYn=Y`)로 discovery 가능(엔드포인트·파서 전부 일반 크롤과 공유). **마감세일은 매일 17시 오픈**(JS `targetDate=…170000` 확인)이라 오픈 전엔 빈 배열이 정상 → **17시 이후 실행 필요**. 상세페이지의 `data-end-time`이 `timedeal_end`로 채워짐.
2. **`is_sold_out`**: 재고상품에서만 검증됨 → 품절 상품 실측으로 셀렉터 확정 필요.
3. **`unit_basis` 혼재**: 대부분 `100g`이나 일부 `1개`/`1구` → 100g 통일은 전처리에서 weight 환산.
4. **`is_fresh_seasonal`**: '햇상품' 이미지 뱃지는 미탐, 상품명 텍스트 기반이라 recall 낮음.
5. **비공식 사설 구조 의존**: 오아시스가 DOM/엔드포인트 바꾸면 파서 깨짐(유지보수 부담) — 마켓컬리와 동일 트레이드오프(§8.4).
