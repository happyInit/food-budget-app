# Elasticsearch(ES) k8s 이관 설계 — AI 검색(recipes)

> **위치/관계**: 이 문서는 인프라 정본 [`docs/k8s-migration-plan.md`](./k8s-migration-plan.md)의 **ES 인프라 골격(ECK 3노드·배치·스토리지·백업)을 보완**하는 **AI측 인덱스/검색 계층 설계**다. 정본은 수정하지 않는다 — 정본에 반영이 필요한 지점은 §11에 제안으로 모아 이슈로 공유한다.
> **대상**: 밥풀이 챗·레시피 서비스가 쓰는 ES 검색 클러스터. ES **8.15.3 / ECK / 3노드 HA / nori**. 네임스페이스 `data`, 클러스터명 `recipes-es`.
> **근거**: 라이브(192.168.0.8:9200) 실측 + 리포 코드. 자원값은 **P4 실측 후 최종 락**.

## 1. 목적과 범위
정본은 "ES를 3노드로 어떻게 띄우고 어디 배치하나"(인프라 골격)까지 확정했다. 이 문서는 그 안을 채우는 **AI 검색 인덱스 계층** — nori 형태소, 인덱스 템플릿(샤드/레플리카/매핑), 샤드 배치 인식, 서빙 인덱스 정책, 재색인·컷오버, 앱 전환, 그리고 **배포 오브젝트 9종 시방서** — 를 설계한다.

## 2. 확정 결정
| # | 결정 | 요지 |
|---|---|---|
| 1 | ES 설정을 **인덱스 템플릿**으로 이관 | 배치 인덱서에 박힌 `replicas:0` 하드코딩을 걷어내고, 설정을 클러스터/GitOps가 소유 → 환경 변화에 어긋나지 않음 |
| 2 | 서빙 SSOT = **`recipes`(배치 인덱서)** 유지 | 이관과 서빙정책 변경을 분리("한 번에 하나만"). CDC(`recipes_pgsync`) 전환은 미래 별도 과제 |
| 3 | ECK 보안 = **인증 유지(TLS+auth) + ESO 주입** | ECK 기본을 그대로. ESO가 이미 표준이라 자격증명 배선 부담이 작고 이식성·심층방어 확보 |

## 3. 현재 실측 베이스라인
| 항목 | 값 | 출처 |
|---|---|---|
| ES 버전 | 8.15.3, analysis-nori 설치·사용 | 라이브 |
| `recipes` | shards 1 · **replicas 0** · 5,425건 · 1.8MB · green | 라이브 |
| `recipes_pgsync` | shards 1 · replicas 0 · 8,230건 · 4MB · green (서빙 미사용) | 라이브 |
| 인덱스 실디스크 총합 | **5.9MB** | `_cat/allocation` |
| 현 노드 heap | 512MB 중 **26% 사용**(ram 1.5GB) | `_cat/nodes` |
| 분석기 `korean` | nori_tokenizer(mixed)+nori_readingform+lowercase | `pipelines/ingest/index_recipes_es.py` |
| 소비자 | 챗(`index="recipes"` 하드코딩)+레시피(`es_index="recipes"`) | `services/chat`, `services/recipe` |
| 인프라 RAM 예산 | ES 3×1.5GB=4.5GB, 배치 B에 2·A에 1 | 정본 §5.2/§2.2 |

## 4. 인덱스 계층 설계
- **nori(최우선)**: ECK 기본 이미지엔 nori가 없어 `korean` 분석기 매핑이 실패한다 → 한국어 검색 붕괴. **`analysis-nori`를 8.15.3 이미지에 bake**한 커스텀 이미지를 쓴다(플러그인은 ES 버전 정확일치 필수). initContainer 설치 방식은 재기동마다 재설치라 기각.
- **인덱스 템플릿(결정1)**: `recipes*` 패턴에 `number_of_shards:1`(6MB엔 단일 샤드가 관련성·오버헤드 최적) + `number_of_replicas:1`(HA) + `korean` 분석기 + 현행 매핑 1:1을 담아 **재색인 전에 등록**. 배치 인덱서에서 `SETTINGS` 하드코딩을 제거해 인덱서는 문서 write만 담당.
- **샤드 배치 인식**: `replicas:1`은 원본·복제본이 **다른 물리호스트**에 있어야 HA가 성립한다. 3노드가 B:2/A:1로 배치되므로, 인식 없이 두면 둘 다 호스트 B에 몰릴 수 있다. `node.attr.host` + `cluster.routing.allocation.awareness.attributes:host`로 **호스트 교차 배치를 강제**한다(정본 §2.4 토폴로지 라벨 재사용 = 신규부담 0).
- **서빙 SSOT(결정2)**: 챗·레시피가 쓰는 `recipes`는 **배치 인덱서**(`index_recipes_es.py`, 품질게이트 `source='10K'` + 미매칭재료 0) 산출물이며 **pgsync가 아니다**. `recipes_pgsync`는 CDC 타깃(서빙 미사용). 정본 P4의 "PG에서 재색인(**PGSync 포함**)"은 이 둘을 뭉뚱그린 부정확한 서술 → 분리(§8). 재색인 = 배치 재실행, pgsync = 타깃 repoint.

## 5. 자원 설계 (3중 근거 + P4 게이트)
자원값은 **①현재 실측 → ②이관 후 3노드 설계 → ③P4 실측**의 3중 확인 후 락한다.
- **① 현재**: heap 실사용 ≈133MB(512m의 26%), 디스크 5.9MB → 절대 수요 극소.
- **② 이관 후**: 3 JVM(파드별 독립 힙) · replicas로 디스크 2배(~12MB, 무시가능) · 코퍼스가 10~20배 성장해도 인덱스 <150MB → **FS 캐시에 통째 상주**. ES 성능은 오프힙 FS 캐시가 좌우하므로 힙은 작게(768m), 나머지 ~700m은 캐시로. RAM 4.5GB는 워커당 13~14GB·여유 ~20GB 내 여유 수용.
- **③ P4 게이트**: 신 3노드에 대표 쿼리 부하 → heap peak·GC·FS캐시 hit·p99 측정 후 락. 기본값 **1.5Gi/768m**(정본 예산 정합), heap peak가 크게 밑돌고 타 RAM 압박 시 1Gi/512m 하향 여지(근거 있을 때만).

## 6. 배포 오브젝트 마스터 표
draw.io 표기용 배지 — STS=StatefulSet · Deploy=Deployment · DS=DaemonSet · Job=일회성 · Svc=Service · PVC · Secret · SM=ServiceMonitor · NP/CNP=NetworkPolicy · PDB=PodDisruptionBudget · CR/CRD.

| 구성요소 | Kind | 상세 설정 | 근거 |
|---|---|---|---|
| ECK 오퍼레이터 | «STS» `elastic-operator`(ns elastic-system) | ECK ≥2.14(ES 8.15 지원) | ECK 자체가 상태보관 STS |
| ES 클러스터 선언 | «CR» `recipes-es` | version 8.15.3, nodeSets a:1/b:2, image=…-nori | 3노드 HA + nori |
| ES 데이터 노드 | «STS» ×3 | node.roles 전역할 | 소량 데이터→역할분리 과설계, 3 master=quorum |
| 노드 sysctl 튜너 | «DS»(선택) | vm.max_map_count=262144 | initContainer와 택1(기본 init) |
| ES 데이터 볼륨 | «PVC» | RWO·openebs-lvm·5Gi·WaitForFirstConsumer | 실5.9MB+머지2×+성장, RWX 금지 |
| 질의 | «Svc» es-http ClusterIP | 9200 HTTPS | 앱 eshost |
| discovery | «Svc» es-transport Headless | 9300 | 노드간 클러스터링 |
| 계정/인증서 | «Secret» ×3 | elastic-user·http-certs·transport-certs | ECK 자동, 결정3 인증 |
| 정족수 보호 | «PDB» | ECK 자동 maxUnavailable:1 | 드레인/업그레이드가 2/3 유지 |
| 인덱스 템플릿 | «Job» PostSync | recipes* → shards1/replicas1/korean/매핑 | 재색인 前 1회 |
| recipes 재색인 | «Job» | index_recipes_es.py(게이트 유지), SETTINGS 제거 | 컷오버 1회, PG서 재생성 |
| pgsync(CDC) | «Deploy» | ES타깃→es-http+creds | 서빙 미사용 상시동기 |
| 앱 자격증명 | «CR» ExternalSecret(ESO) | ES 유저/비번→앱 ns | 정본 §6.4 |
| ES exporter | «Deploy»+«SM» | es-http+creds, 30s | 정본 §9 관측 |
| 접근통제 | «NP»/«CNP» | 앱4종→9200만, DNS·S3 egress 예외 | 정본 §6.1 |
| 스냅샷(SLM) | ES 내부 정책 | S3, 14/02시·14d, Glacier금지 | 정본 §6.3 |
| **HPA** | **없음** | quorum 3 고정, 확장=nodeSet 수동 | 스테이트리스 앱만 HPA |

## 7. ES 시방서 (별도 파일)

오브젝트 9종(«CRD»«CR»«STS»«PVC»«SVC»«Secret»«NP»«CNP»«Job»)의 매니페스트 수준 명세와 각 설정의 한 문장 근거는 **별도 시방서** [`docs/es-spec.md`](./es-spec.md)로 분리했다. 배포 오브젝트 요약표는 위 §6 참고.

## 8. 컷오버 순서 (정본 P4 정정판)
```
① ECK 번들(«CRD»+오퍼레이터STS)
② «CR» recipes-es (→ «STS»2·«PVC»3·«SVC»2·«Secret»)  # initContainer vm.max_map_count 포함
③ «Secret» es-s3-creds·앱creds(ESO)
④ «Job» es-index-template            # nori 매핑 템플릿, 재색인 前 필수
⑤ «Job» es-reindex-recipes           # recipes = 배치 재색인 (pgsync 아님)
⑥ pgsync ES 타깃 repoint             # recipes_pgsync (서빙 미사용)
⑦ «NP»+«CNP» 적용
⑧ 검증: docs.count·green·nori 분석 동작·replica가 호스트 교차 배치됐는지
⑨ 앱 eshost 스위치 → 구 ES 폐기
```
**정정 포인트**: 정본 P4 "PG에서 재색인(PGSync 포함)"은 부정확 — 서빙 인덱스 `recipes`는 배치 인덱서 산출물이고 pgsync가 아니다. 두 파이프라인을 분리 기술한다.

## 9. 앱 컷오버 (AI측 변경점)
| 앱 | 현재 | 변경 |
|---|---|---|
| 챗 | `eshost=.8`, `index="recipes"` 하드코딩, 무인증 | `eshost`→es-http DNS + ES 자격증명·TLS CA(ESO). 인덱스명 유지. (선택: `ES_INDEX` env화 → blue/green 용이 = 별도 이슈) |
| 레시피 | `eshost=.8`, `es_index="recipes"`, 무인증 | 동일. 인덱스명 이미 파라미터화 |
| 배치 인덱서 | `es_client()`(.8), SETTINGS 하드코딩 | ECK 엔드포인트+creds, **SETTINGS 제거**(템플릿 소유) |

## 10. 설정 근거 — 한 문장 설명 (팀 공유용)
- **«CRD»**: ECK를 설치하면 자동으로 생기는 '설정 양식'이라, 이게 있어야 우리 ES 설정을 쿠버네티스가 알아듣는다.
- **nori 이미지**: 한국어 형태소 분석기를 기본 이미지에 미리 구워 넣어야 레시피가 한국어로 제대로 검색된다.
- **버전 8.15.3 고정**: 지금 버전과 똑같이 못 박아야 플러그인·매핑이 어긋나지 않는다.
- **노드 A에 1·B에 2 + host 딱지(awareness)**: 3대를 물리서버를 갈라 배치하고 원본·복제본이 같은 서버에 몰리지 않게 강제해, 한쪽 서버가 죽어도 데이터가 산다.
- **힙 768m / 메모리 1.5Gi 고정(요청=상한)**: ES엔 메모리 절반만 주고 나머지는 검색속도용 캐시로 남기며, 몫을 최소=최대로 잡아 메모리 부족으로 죽는 걸 막는다.
- **initContainer(sysctl)**: ES가 켜지기 전 꼭 바꿔야 하는 커널값을 파드 시작 시 자동으로 해준다.
- **StatefulSet 사용**: ES는 고유 이름과 자기 디스크를 유지해야 해서 Deployment가 아니라 StatefulSet으로 띄운다.
- **PDB(동시 1대만) / HPA 없음**: 여러 대가 한꺼번에 꺼지면 정족수가 깨지므로 동시 1대만 꺼지게 막고, 3대 정족수가 고정이라 오토스케일은 붙이지 않는다.
- **PVC RWO·5Gi / storageClass 변수화**: ES 디스크는 한 파드만 붙잡는 방식(클라우드 디스크와 동일→AWS 이식 그대로)이고, 실데이터는 작지만 내부정리·성장 여유로 5GB, 이름만 바꾸면 온프렘/AWS 전환된다.
- **es-http / es-transport**: 앞의 것은 앱이 검색을 보내는 대표 주소(앱은 이 이름만 봄), 뒤의 것은 ES끼리 무리를 이루는 내부 통로.
- **Secret들**: ES 로그인 비번·TLS 인증서를 ECK가 자동 생성하고, 백업 S3 열쇠와 앱 계정은 외부 비밀저장소(ESO)에서 자동 주입한다.
- **NP / CNP**: ES 접근을 앱 4종으로만 제한하며, 표준규칙(NP)은 이사용·Cilium규칙(CNP)은 실제 강제용으로 함께 두고, DNS와 백업 S3 나가는 길은 반드시 열어둔다.
- **인덱스 템플릿 Job(샤드1/복제본1/매핑보존)**: 레시피를 담기 전에 조각 수·사본 수·한국어 분석기·필드 형식을 미리 정하는 '틀'을 한 번 등록하며, 데이터가 작아 조각은 1개·사본은 1벌, 필드 형식은 지금 챗이 쓰는 그대로 옮긴다.
- **재색인 Job / 스크립트에서 설정 제거**: 레시피를 원본 DB에서 새 ES로 다시 채우는 일회성 작업(DB에서 언제든 재생성 가능해 안전)이고, 설정은 이제 '틀'이 맡아 환경이 바뀌어도 어긋나지 않는다.

## 11. 정본 반영 제안 (인프라 담당자 협의 — 정본 수정은 담당자 몫)
아래는 정본 `k8s-migration-plan.md`에 반영되면 좋을 지점. **이 문서에서 정본을 직접 고치지 않고 이슈로 제안**한다.
1. **§5.2 ES / 체크리스트**: `analysis-nori(8.15.3) 이미지 bake` + `allocation awareness(호스트 교차)` 추가 — 없으면 재색인 첫 삽에서 매핑 실패.
2. **§10 P4**: "PG에서 재색인(PGSync 포함)" → **배치(recipes) + pgsync(recipes_pgsync) 분리** 정정 + 재색인 순서(§8) 반영.
3. **인덱스 템플릿 선적용**을 컷오버 체크리스트 항목으로 추가(재색인 前).
4. **협의 필요 3건**: ① 토폴로지 라벨을 `node.attr.host` awareness로 노출(신규부담 0) ② nori bake 이미지 레지스트리 경로(Harbor→ECR) ③ «Job»(템플릿/재색인) 소유 위치(AI 레포 vs config 레포) + ArgoCD PostSync 훅.
