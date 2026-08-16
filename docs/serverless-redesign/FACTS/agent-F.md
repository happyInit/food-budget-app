# FACTS/agent-F.md — PF-02·03·14 판정 (B단계, 2026-08-07)

## 1. 판정 요약표

| ID | 제목 | 심각도 | 판정 | 근거(URL+조회일 또는 파일:라인) | 조치(수정/불필요/보류) | 행번호 정정 |
|---|---|---|---|---|---|---|
| PF-02 | Bedrock 서울 리전 모델 가용성·추론 프로파일 | critical | **사실** | `11_실측발견_2026-08-07.md §1`(CLI 원문 `FACTS/bedrock-models-apne2.json`·`bedrock-profiles.json`) + https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html [조회 2026-08-07] | **수정**(카드 수정안 1~6 채택, 실 ARN 기입) | 정정 없음 |
| PF-03 | 모델 액세스·쿼터 상향 리드타임 미배치 | critical | **부분적으로 사실** | https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html · https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-runtime.html · https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html · https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html [전부 조회 2026-08-07] + CLI AccessDenied 실측 | **수정**(액세스 신청 항목은 불필요 — 적용값 조회 태스크·IAM 읽기권한 부여로 대체) | 정정 없음 |
| PF-14 | 청구 데이터 지연·크레딧 차감 후 표시 | high | **부분적으로 사실** | https://docs.aws.amazon.com/cost-management/latest/userguide/ce-what-is.html · https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-credits.html [조회 2026-08-07] + `01_...일정...md:394-395` | **수정**(카드 수정안 1~4 채택, 단 '기준선 착시' 서술은 완화) | 정정 없음 |

## 2. 카드별 판정 기록

### PF-02 Bedrock 서울 리전 모델 가용성·추론 프로파일 — 판정: 사실

- 검증할 명제: 채택 모델 2종이 서울 온디맨드 직접 호출인지 APAC 프로파일 필수인지 미확인 — 프로파일 필수면 '양쪽 서울' 전제 충돌 + 모델 ARN 한정 IAM은 AccessDenied.
- 행번호 재확인: 전수 일치 — `02_Phase1_아키텍처_설계.md:174,177,178`("`bedrock:InvokeModel` (… ARN 한정)")·`:226`("### 4-2. Bedrock VPC 엔드포인트"), `01_Phase1_일정_AI서버리스.md:265`(`ai-bedrock-invoke`)·`:50-51`(외부 호출 목적지), `03_Phase1_실행_체크리스트.md:153`("Bedrock 권한 — 모델 ARN 한정")·`:176`("엔드포인트 정책으로 모델 한정" — VPC 엔드포인트 생성 자체는 L175, 보충), `06_검증_시나리오.md:144-146`(nova-micro·sonnet-3.5·Vertex 행), `REVIEW_BRIEF_claude_code.md:211`. 정정 없음.
- 공식 문서 확인: https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html [조회 2026-08-07], 인용: "When you choose an inference profile tied to a specific geography, Amazon Bedrock automatically selects a commercial AWS Region within that geography to process your inference request." (+ 동일 페이지 SCP 요건 행: "Allow all destination Regions in profile" — 정책은 프로파일의 전 목적지 리전을 허용해야 함)
- CLI 실증: 재실행 안 함(사용자 지시 — 기계 근거 확정 재확인만).
- 실물 대조: `11_실측발견 §1` — apne2 ON_DEMAND 5종뿐, 채택 2종(`amazon.nova-micro-v1:0`·`anthropic.claude-3-5-sonnet-20241022-v2:0`)은 INFERENCE_PROFILE 전용, APAC 프로파일 = 도쿄·서울·싱가포르·시드니·뭄바이 5리전. `02_as_built.md` D-19 — 실물 코드가 이미 `apac.` 프로파일 ID 사용(리뷰 요약 `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`, 감정·소비기한 `apac.amazon.nova-micro-v1:0`).
- ⚠️ 함정 확인: 'sonnet-3.5' 버전 분리 필수 — v2(20241022)=프로파일 전용, v1(20240620)=서울 ON_DEMAND라 버전 미특정 시 정반대 결론이 나온다. 라우팅 리전(5개, 전부 아태)을 판정보다 먼저 기록했다 → 'APAC 역내' 재정의(11_실측 §6 안 A)가 열려 있어 판정에 영향 없음.
- 판정 이유: 채택 모델 2종 모두 서울 단독 호출 불가(프로파일 필수)가 기계 근거로 확정 — '양쪽 서울 리전' 전제는 붕괴하고, 프로파일 호출은 공식 문서상 지리 내 임의 리전에서 처리되므로 foundation-model ARN 단독 한정 IAM 설계는 성립하지 않는다(프로파일 ARN + 목적지 리전 모델 ARN 동시 허용 필요, SCP 요건 동일 취지). 카드의 '참' 분기 그대로.
- sonnet-3.5 확정 버전: 실물 = `20241022-v2`(apac. 프로파일 경유, D-19). 서울 ON_DEMAND 대안 = `anthropic.claude-3-5-sonnet-20240620-v1:0` [파일: 11_실측발견 §1·§3].
- 프로파일 라우팅 리전: ap-northeast-1 · ap-northeast-2 · ap-southeast-1 · ap-southeast-2 · ap-south-1 [파일: 11_실측발견 §1-1, CLI 원문 bedrock-profiles.json].
- 수정안: 카드 수정안 1~6 전부 채택. 실 ARN 예시는 `apac.anthropic.claude-3-5-sonnet-20241022-v2:0`·`apac.amazon.nova-micro-v1:0`(+ 대상 5리전 foundation-model ARN) [조회 2026-08-07]. — 수정 지시 1줄: `02` §3-2 세 셀·§4-2, `01` L50~53·L265, `03` L153·L176, `06` §3-2, `08` 레지던시 문장을 "프로파일 ARN + 5개 대상 리전 모델 ARN 허용, 라우팅 = APAC 역내(서울 단독 아님)"로 일괄 교체하라(직접 수정은 이 세션 범위 밖 — 지시만).
- 연동 메모: 레지던시 원칙 재정의(A/B/C안)는 팀 결정 사항 — 11_실측 §6, 단독 확정 금지.

### PF-03 모델 액세스·쿼터 상향 리드타임 미배치 — 판정: 부분적으로 사실

- 검증할 명제: 모델 액세스 활성화·Lambda 동시성 상향·Bedrock TPM/RPM 상향은 즉시 반영이 아닐 수 있는데, 계획에 신청 태스크가 없고 첫 '확인'이 8/13이다.
- 행번호 재확인: 전수 일치 — `01:340`(8/13 절)·`:353-357`(쿼터 확인·상한 설정)·`:455`("쿼터 증설 신청 경로"), `03:218-224`("🔴 외부 API 쿼터 ★ 가장 중요"), `05:37-46`(R-03)·`:230`(추적표 R-03, 최종 확인 8/13), `REVIEW_BRIEF:207`("Lambda 계정 한도"). 정정 없음.
- 공식 문서 확인 [전부 조회 2026-08-07]:
  - 상향 처리 시간: https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html — "Smaller increases are usually automatically approved while larger requests are submitted to Support. Larger increase requests take time to review, process, approve, and deploy."
  - Bedrock 쿼터 조정 가능성: https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-runtime.html — "If a quota is marked as **Yes**, you can adjust it by following the steps at Requesting a Quota Increase"; TPM 계열은 "request an increase for the **Cross-Region InvokeModel tokens per minute** … the support team will reach out"; 거절 가능: "Due to overwhelming demand, priority will be given to customers who generate traffic that consumes their existing quota allocation. Your request might be denied if you don't meet this condition." 신규 계정 감산: "New AWS accounts might receive reduced quotas." (모델별 Adjustable Yes/No 최종 확정은 계정 콘솔/General Reference 표 기준 — 아래 확정 방법)
  - Lambda 한도: https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html — "Concurrent executions | 1,000 | Tens of thousands"(Service Quotas 경유 상향) + "New AWS accounts have reduced concurrency and memory quotas for Lambda Functions … AWS raises these quotas automatically based on your usage."
  - 모델 액세스(선행 확인 재인용): https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html [조회 2026-08-07, 세션 STATE §1 실호출 확인] — Anthropic FTU use case 폼 = 제출 즉시 액세스 부여, 첫 호출 시 백그라운드 Marketplace 구독 최대 15분.
- CLI 실증: `aws service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 --region ap-northeast-2` → **AccessDeniedException**(user/geonu에 `servicequotas:GetServiceQuota` 없음). `aws lambda get-account-settings`·`list-service-quotas --service-code bedrock`도 동일 AccessDenied. **계정 적용값 실측 불가**(11_실측 §7의 "ReadOnly 정책 부여 후" 전제 그대로 미해소).
- 소요 산출: MAU 500 → 일 1,500~2,000건, 피크 30%/2h 가정 시 ≈0.08 req/s, 요청당 1s면 동시 실행 ~0.1 [추정: 2,000×0.3÷7,200s]. 문서상 기본 1,000 [출처: 위 Lambda URL, 조회 2026-08-07] 대비 무시 가능 — 단 계정 **적용값**은 [미확인](신규 계정 감산 명시 조항 존재).
- 모델 액세스 상태: 실물이 이미 `apac.` 프로파일로 일일 배치 실호출 중(감정 07:00 KST, `02_as_built.md` D-19·§2 #8) → nova-micro·sonnet 계열 액세스는 사실상 부여 상태. 신청 태스크 불필요.
- ⚠️ 함정 확인: 함정 그대로 적중 — 실사용 트래픽은 어떤 기본 한도로도 남아돌고("사실이지만 우리 규모에선 무의미" 방향), 진짜 병목 후보였던 액세스 승인은 즉시 부여로 해소, 8/13 인위 부하는 상향 신청이 아니라 목표치 하향이 1차 해법.
- 판정 이유: ① 쿼터 상향의 심사·소요·거절 가능성은 공식 문서로 사실이고 신청 태스크 미배치도 사실. ② 그러나 모델 액세스 절반은 거짓(즉시 부여 + 이미 사용 중). ③ 실사용 규모는 한도 대비 무관 수준이나, 신규 계정 감산 조항 + 적용값 열람 권한조차 없는 현 IAM 때문에 "여유롭다"를 오늘 숫자로 확정할 수 없다 → 부분적으로 사실.
- 수정안: 카드 수정안 중 취사 — '액세스 활성화 신청'은 제외하고, (a) 8/6~7 태스크로 "geonu에 `ServiceQuotasReadOnlyAccess`(+`lambda:GetAccountSettings`) 부여 → Lambda 동시성·Bedrock TPM/RPM **적용값** 조회·기록" 신설, (b) `05`에 R-03A를 '상향 지연·거절'로 축소 신설(1차 대응 = 8/13 목표치를 적용값의 70~80% 이내로 하향, `06` §3-2 원칙과 정합), (c) `01` L455 런북에 "Smaller … automatically approved / larger … take time to review" 취지 병기. — 수정 지시 1줄: 신청 리드타임 태스크 대신 '읽기권한 부여+적용값 조회'를 8/6~7에 배치하고 8/13 목표치 하향 규칙을 명문화하라(직접 수정 금지 — 지시만).
- 확인 불가 잔여분 확정 방법: ReadOnly 정책 부여 후 `aws service-quotas get-service-quota --service-code lambda --quota-code L-B99A9384 --region ap-northeast-2` + `aws service-quotas list-service-quotas --service-code bedrock --region ap-northeast-2`(Adjustable 열 포함), 콘솔 = Service Quotas → Amazon Bedrock/Lambda.

### PF-14 청구 데이터 지연·크레딧 차감 후 표시 — 판정: 부분적으로 사실

- 검증할 명제: 비용 데이터는 최대 24~48h 지연되고 기본 뷰는 크레딧 적용 후 금액 → 8/15에 8/13~14 실측을 온전히 못 보고, 기준선 4,577원 대비 실소비가 과소평가된다.
- 행번호 재확인: 전수 일치 — `03:255`("실제 청구 데이터 확인 (며칠치라도)")·`:256-266`, `06:178`(§4-1 "실제 청구 기준")·`:193`(합계 4,577원)·`:26`(기준선), `01:391-424`(8/15 절)·`:394-395`("기존: 월 4,577원 (MAU 500, AWS 크레딧 부담 247원)" / "이것은 LLM 토큰 비용만의 숫자다"), `05:170`("비용이 예상의 5배 초과")·`:120-127`(R-10), `04:9·17`(진입 게이트 "비용이 예상 범위 내"). 정정 없음.
- 공식 문서 확인 [전부 조회 2026-08-07]:
  - 지연: https://docs.aws.amazon.com/cost-management/latest/userguide/ce-what-is.html — "Cost Explorer refreshes your cost data at least once every 24 hours. However, this depends on your upstream data from your billing applications, and some data might be updated later than 24 hours." (+ 최초 활성화 시 "The current month's data is available for viewing in about 24 hours.")
  - 크레딧: https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-credits.html — "AWS credits are automatically applied to bills to help cover costs that are associated with eligible services. … Credits are applied until they are exhausted or they expire." 잔액·만료일·적용 상품은 Billing 콘솔 Credits 페이지의 "Amount remaining"·"Expiration date"·"Applicable products" 항목(잔액 확정치는 청구 사이클 말 갱신, 당월 추정치는 일 단위 갱신).
- CLI 실증: `aws ce get-cost-and-usage --time-period Start=2026-07-31,End=2026-08-08 --granularity DAILY --metrics UnblendedCost NetUnblendedCost --region us-east-1` → **AccessDeniedException**(`ce:GetCostAndUsage` 미허용) — 실측 지연 일수·RECORD_TYPE 필터 전후 차이·크레딧 잔액은 오늘 실측 불가. 확정 방법: geonu에 `ce:GetCostAndUsage` 허용(또는 Billing 읽기 정책) 후 카드 2·3단계 명령 재실행 / 콘솔 = Billing and Cost Management → Cost Explorer·Credits.
- 실물 대조: 크레딧 $700은 계획 문서 주장(`02_as_built.md` §0 전제) — 잔액·만료일 [미확인]. 4,577원의 실제 정의 = `01:394-395` "LLM 토큰 비용만의 숫자"(크레딧 부담 247원 병기) — 청구화면 숫자가 아니라 토큰 단가 계산치다.
- ⚠️ 함정 확인: 두 함정 다 실재 — ① L394~395 정의 확인으로 '기준선이 크레딧 착시'라는 후반부는 문서 실제와 어긋남을 확정(CS-02와 상충 금지 원칙 준수), ② `--region us-east-1`은 준수했으므로 AccessDenied는 리전 오판이 아니라 IAM 권한 문제로 명시.
- 판정 이유: ① 지연 전반부는 공식 문서로 사실(24h 주기 + 그 이상 가능 → 8/15에 8/14분 미반영 가능성 실재. 단 '최대 48h'라는 상한 명시는 문서에 없음 — "later than 24 hours" 개방형). ② 크레딧은 자동 적용되어 청구 표시에 반영되나 Credits 페이지·RECORD_TYPE 필터로 분리 가능 — 카드 판정지 문구 그대로 "부분적으로 사실(RECORD_TYPE 필터로 분리 가능)". ③ '기준선 4,577원 과소평가' 후반부는 기준선이 청구 데이터가 아니므로 성립하지 않음. ④ 계정 실측치는 IAM 권한 부재로 미측정(위 확정 방법).
- 수정안: 카드 수정안 1~4 채택, 단 문구는 '기준선 착시'가 아니라 "8/15 숫자는 잠정치(미반영분은 요금 계산기 추정으로 보충·출처 표기) + 크레딧 전/후 열 분리 + 크레딧 잔액·만료일 콘솔 캡처를 8/15 산출물로 명시"로. — 수정 지시 1줄: `03` L255 교체·크레딧 체크박스 4개 추가, `06` §4-1 열 확장(적용 전/후/출처), `05` R-13 신설·L170 '크레딧 적용 전 실비 기준' 한정을 반영하라(직접 수정 금지 — 지시만).
- 연동 메모: **CS-02 판정 시 이 결론을 승계할 것** — 4,577원 = `01:394-395` 정의상 'LLM 토큰 비용만'의 계산치(AWS 크레딧 부담 247원 병기)이며 청구 표시 금액이 아니다. 두 카드가 이 정의를 공유해야 비용 슬라이드가 일관된다.

## 3. 진단서 결함 목록

- 없음 — 세 카드의 앵커 행번호 전수 일치(경미: PF-02의 `03` L176은 "엔드포인트 정책으로 모델 한정"이고 "VPC 엔드포인트 생성"은 L175 — 카드 취지와 부합, 정정 불요). 부기: PF-02 검증 단계 1·2의 CLI는 `11_실측발견`으로 이미 수행 완료라 카드 절차가 중복이며, PF-03·PF-14의 CLI 검증 단계는 현 IAM(user geonu)의 읽기 권한 부재를 전제하지 않았다(servicequotas·lambda:GetAccountSettings·ce:GetCostAndUsage 전부 AccessDenied — 검증 자체에 선행 IAM 태스크가 필요).
