# PRD — 공공데이터 검증·스키마·PostgreSQL 적재 (서비스 확인용)

> 작성 2026-07-13 · 브랜치 `feat/app-data-restructure`
> ⚠️ `docs/design.md`(SSOT) 미수정. 이 PRD는 데이터 계층을 서비스에 붙여보는 **실행 계획서**.
> 소스 검증 = 2026-07-13 primary source 확인 완료(§4). 스키마 = `docs/prd/schema-public-data.sql`.

## 1. 배경
- restructure 논의로도 **서비스 기능은 거의 불변**(바뀐 건 축·데이터소스·가격비교 제거 3가지, `data-gap-analysis.md`).
- 분업: **크롤링(만개레시피·오아시스몰·컬리마켓·핫딜) = 팀원**, **공공데이터 = 우리**.
- 목적: 공공 소스를 **검증 → 실제 컬럼 확인 → 서비스별 스키마(DDL) → PostgreSQL 소량 적재**. 대량 아님, **서비스 동작 확인용**.

## 2. 목표 / 비목표
**목표**: 확정 공공 소스의 liveness·컬럼·라이선스 검증(참가격 사망 선례→trust-but-verify) · 서비스별 스키마 DDL · 샘플 적재로 서비스 쿼리 경로 확인.
**비목표**: 대량/전량 적재, 실시간 파이프라인(Kafka), 크롤 소스 적재(팀원), 최저가 비교·가격이력·시세예측(드롭/보류).

## 3. 스코프 — 소스 ↔ 서비스 매핑
| # | 공공 소스 | → 서비스/테이블 | 상태 |
|---|---|---|---|
| 1 | 식약처 식품영양성분 DB | Recipe(영양성분)·품목마스터 / `food_nutrition` | ✅ 생존 |
| 2 | 식약처/KFIA 소비기한 참고값 | Pantry / `shelf_life_ref` | ⚠️ PDF뿐, 샘플 수기 |
| 3 | USDA FoodKeeper (CC0) | Pantry / `shelf_life_ref` | ✅ 생존(정적) |
| 4 | 공공 레시피 COOKRCP01·농교원 EPIS | Recipe / `recipe*` | ✅ 둘 다 생존 |
| 5 | 통계청/국가데이터처 온라인가격 15080757 | Price / `price_online_daily` | ✅ 생존(키 필요) |
| — | 한국소비자원 참가격 | — | ❌ API 사망 → 제외 |

## 4. 소스별 검증 결과 (2026-07-13, primary source)
- **[1] 영양성분** ✅ 4계열 분산. 권장 신규 통합 API **15127578**(실시간, JSON+XML, 이용허락 제한없음, 296,163건) / 표준데이터 **15100064**(45컬럼, 미네랄·비타민, CSV 등 5포맷 다운로드·무키) / 경량 레거시 **I0750**(9영양소). ⚠️ I2790은 2023서 멈춤(사용금지). 매칭키 `FOOD_CD·식품명·분류코드`.
- **[2] KFIA 소비기한** ⚠️ **정형 데이터 아님** — OpenAPI·CSV·data.go.kr 전부 없음. 검색 UI(2,037건/204유형) + **품목별 PDF**, 소비기한 일수 값이 **PDF 내부**. 라이선스(KOGL) 미표기=회색. → 대량적재 불가, **대표 샘플 수기 입력**.
- **[3] USDA FoodKeeper** ✅ **CC0**. XLS/JSON(공식 CSV 없음). Product 661건, Category 10대분류/25조합, 8 보관시나리오×(Min/Max/Metric), Metric에 상태값(When Ripe 등) 혼재. ⚠️ 라이브 **Akamai 403**→Wayback/미러(2018 이후 정적, 1회 다운로드로 충분). US 기준→한식 매핑률 낮음.
- **[4] 공공 레시피** ✅ 둘 다 생존·상반.
  - COOKRCP01(15060073, 제한없음, JSON+XML, sample키 존재, ~1,000건, 55필드): 재료 `RCP_PARTS_DTLS`=**자유텍스트→CRF NER 대상**. 저염·건강 큐레이션.
  - 농교원 EPIS 3종(15057205/15058981/+과정, RECIPE_ID 조인, 제한없음): 재료 **정형(1재료=1행 `IRDNT_NM`+`IRDNT_CPCTY`)→NER 학습 라벨 소스**. host `211.237.50.150:7080`.
- **[5] 15080757** ✅ **생존**(404 아님, 최종수정 2025-09-08, 제한없음). 제공기관 통계청→**국가데이터처** 개명. REST+serviceKey, XML, ~120품목(집계가), 일별. 품목리스트 필드 `rn·ic·in` 확인, **가격조회 필드는 serviceKey 발급 후 확정**.

## 5. 스키마 — `docs/prd/schema-public-data.sql`
- `food_nutrition` — 영양성분(9영양소, 표준데이터 시 미네랄 확장).
- `shelf_life_ref` — KFIA+FoodKeeper 통합, 8 보관시나리오 wide→행 melt, 상태값 unit 흡수.
- `recipe`/`recipe_ingredient`/`recipe_step` — COOKRCP01+EPIS 정규화. **`recipe_ingredient.ner_status`로 EPIS(정답라벨) vs COOKRCP01(NER대상) 구분 = NER seam**.
- `price_item`/`price_online_daily` — 15080757, serviceKey 후 필드 확정 조건부.

## 6. 적재 방식 — 2단계 (인증키 부트스트랩)
**Phase 1 (무키, 즉시)**: 인증키 없이 되는 것부터.
- 영양성분 = **표준데이터 15100064 CSV/JSON 다운로드**(무키).
- 소비기한 = **FoodKeeper Wayback JSON**(무키) melt + **KFIA 대표 샘플 수기**.
- 레시피 = COOKRCP01·EPIS **sample 키**(각 5건)로 스키마·쿼리 경로 확인.

**Phase 2 (키 확보 후)**: data.go.kr/식품안전나라 활용신청 → 레시피 전량(~1,000) · **Price(15080757)** 적재 + 가격조회 필드 확정.

- 언어 Python(파이프라인 통일). OpenAPI/파일 → 파싱 → 멱등 upsert. 대상 = fb-data(.8) `foodbudget` DB(tfstate-db와 공유 인스턴스·DB 분리). `source`·`fetched_at` 메타.
- 비밀(키): gitignore secrets에 사용자 편집, 에이전트는 값 미열람.

## 7. 완료 정의
- [ ] 소스 liveness·라이선스 문서화(완료, §4).
- [ ] DDL 적용 + Phase 1 샘플 적재.
- [ ] 서비스 대표 쿼리 통과: 재료→영양 조인 / 품목→소비기한 참조 / 레시피→재료·순서.
- [ ] Phase 2 키 확보 시 Price·레시피 전량 확장.

## 8. 리스크
- 참가격 사망 선례 → 소스는 언제든 죽을 수 있음(재검증 유지).
- KFIA PDF·라이선스 회색 → 소량 참조용에 한정.
- 자유텍스트 품목·재료명 → 품목마스터 매칭이 load-bearing(벤치마크 §4-3 "아무도 문서화 안 한 공백"). EPIS 정형 재료가 그 부트스트랩.
- anti-bot 우회 전제 금지(공공 API·다운로드·아카이브만).

## 9. 산출물 / 이슈
- 이 PRD + `schema-public-data.sql` + Phase 1 적재 스크립트 + 검증 로그.
- **GitHub 이슈 = 서비스별 3개** (레포 `happyInit/food-budget-app`):
  1. [#4](https://github.com/happyInit/food-budget-app/issues/4) Pantry — 소비기한 참조표(FoodKeeper + KFIA 샘플)
  2. [#5](https://github.com/happyInit/food-budget-app/issues/5) Recipe — 영양성분 + 공공 레시피(COOKRCP01·EPIS, NER seam)
  3. [#6](https://github.com/happyInit/food-budget-app/issues/6) Price — 온라인가격 baseline 15080757 (Phase 2, 키 blocked)
