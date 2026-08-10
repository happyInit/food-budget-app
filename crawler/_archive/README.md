# crawler/_archive — 완료된 일회성 백필 (보관)

임무를 마친 **일회성 백필 스크립트**를 보관한다. 정규 파이프라인(CronJob·Deployment·config)에서
참조하지 않고 실행되지 않는다. 유사 사고 시 "영향분만 재크롤" 패턴의 참조로 코드째 남긴다.

## recipe_thumbnail_backfill.py
- **목적**: 썸네일 병합(`6006bb0`, 2026-07-16) *이전* 크롤된 레시피의 썸네일 소급 채움.
- **완료 근거**: 10K 레시피 7,444개 전부 썸네일 보유(누락 0). 썸네일 추출 로직은
  `crawler/10k_recipe/10k_recipe_crawler.py`(`extract_thumbnail_url`, 상세페이지 재요청 없이 같은 파싱)에 병합됨.

## reparse_buy_link_backfill.py
- **목적**: `'구매'` 재료명 파싱버그(2026-07-21 실측 446레시피 / 510행) 영향분 재크롤 → Kafka 재발행.
- **완료 근거**: `public.recipe_ingredient`의 `ingredient_name/ingredient_raw = '구매'` 잔량 0.
  근본원인은 `10k_recipe_crawler.py`의 `extract_ingredients()`(`.ingre_list_name` 선택자 + 구매버튼 제외 폴백)로 수정됨.
- ⚠️ **재실행 시**: 메인 크롤러를 상대경로(`_HERE.parent / "10k_recipe_crawler.py"`)로 로드하므로,
  이 위치(`crawler/_archive/`)에서는 경로가 어긋난다 — 재발동이 필요하면 경로 조정 필요.

> 두 스크립트 모두 재발동 예정 없음. git 이력 대신 코드로 보존해 소급/참조 가치를 남긴다.
