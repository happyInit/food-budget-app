# Elasticsearch(ES) k8s 이관 시방서 — AI 검색(recipes)

> **관련**: 배경·결정·근거는 설계서 [`docs/es-k8s-migration-design.md`](./es-k8s-migration-design.md) 참고. 이 문서는 그 §7 시방서의 정식 분리본이다.

> 대상: 밥풀이 챗·레시피 서비스가 쓰는 ES 검색 클러스터. ES **8.15.3 / ECK / 3노드 HA / nori**.
> 근거: 라이브(192.168.0.8:9200) 실측 + 리포 코드. 값은 **P4 실측 후 락**(자원). 배포 오브젝트 9종을 명세한다.
> 네임스페이스: `data` (정본 §5.1). 클러스터명(예): `recipes-es`.

## 오브젝트 인덱스
| # | Kind | 이름 | 관리 | 개수 |
|---|---|---|---|---|
| 1 | **CRD** | `elasticsearches.elasticsearch.k8s.elastic.co` | ECK 번들 | 1 |
| 2 | **CR** | `recipes-es` (Elasticsearch) | ArgoCD | 1 |
| 3 | **STS** | `recipes-es-es-zone-a`(1) · `-zone-b`(2) | ECK 생성 | 2(파드3) |
| 4 | **PVC** | `elasticsearch-data-…`(volumeClaimTemplate) | STS 생성 | 파드당 1 |
| 5 | **SVC** | `recipes-es-es-http` · `-es-transport` | ECK 자동 | 2 |
| 6 | **Secret** | elastic-user · http-certs-public · s3-creds 등 | ECK/ESO | 4+ |
| 7 | **NP** | `es-ingress-9200` | ArgoCD | 1 |
| 8 | **CNP** | `es-cilium` (L3 ingress + S3 egress FQDN) | ArgoCD | 1 |
| 9 | **Job** | `es-index-template` · `es-reindex-recipes` | ArgoCD | 2(1회성) |

---

## 1. «CRD» Elasticsearch (ECK가 설치 — 문서화만)
```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata: { name: elasticsearches.elasticsearch.k8s.elastic.co }
spec:
  group: elasticsearch.k8s.elastic.co
  names: { kind: Elasticsearch, plural: elasticsearches, shortNames: [es] }
  scope: Namespaced
  versions: [{ name: v1, served: true, storage: true }]
```
- **상세**: ECK 오퍼레이터 번들(«STS» elastic-operator, ns elastic-system) 설치 시 함께 등록. 손으로 작성하지 않음.
- **근거**: 이 CRD가 있어야 아래 «CR»을 API가 인식. ECK ≥2.14 = ES 8.15 지원.

## 2. «CR» Elasticsearch `recipes-es` (설계의 본체)
```yaml
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: Elasticsearch
metadata: { name: recipes-es, namespace: data }
spec:
  version: 8.15.3
  image: harbor.local/library/elasticsearch:8.15.3-nori   # nori bake 커스텀
  secureSettings:
    - secretName: es-s3-creds        # S3 키를 ES keystore로 주입(스냅샷용) → Secret #6
  nodeSets:
    - name: zone-a                   # 호스트 A (1)
      count: 1
      config:
        node.roles: [master, data, ingest, remote_cluster_client]
        node.attr.host: a
        cluster.routing.allocation.awareness.attributes: host
      podTemplate: &pod
        spec:
          initContainers:
            - name: sysctl
              securityContext: { privileged: true }
              command: ['sh','-c','sysctl -w vm.max_map_count=262144']
          containers:
            - name: elasticsearch
              env: [{ name: ES_JAVA_OPTS, value: "-Xms768m -Xmx768m" }]
              resources:
                requests: { memory: 1.5Gi, cpu: 500m }
                limits:   { memory: 1.5Gi, cpu: "1" }
          affinity:                  # 호스트 A 노드에만
            nodeAffinity: { requiredDuringScheduling: { host=A } }
      volumeClaimTemplates: &vct
        - metadata: { name: elasticsearch-data }
          spec:
            accessModes: [ReadWriteOnce]
            storageClassName: openebs-lvm
            resources: { requests: { storage: 5Gi } }
    - name: zone-b                   # 호스트 B (2)
      count: 2
      config:
        node.roles: [master, data, ingest, remote_cluster_client]
        node.attr.host: b
        cluster.routing.allocation.awareness.attributes: host
      podTemplate: *pod              # affinity만 host=B로 치환
      volumeClaimTemplates: *vct
```
| 필드 | 값 | 근거 |
|---|---|---|
| `version/image` | 8.15.3 + nori | nori 없으면 `korean` 매핑 실패. 버전 정확일치 핀 |
| nodeSets 2개(a:1,b:2) | 파드 3 · **awareness=host** | replicas:1이 **다른 호스트**에 놓여야 HA(정본§2.2 배치) |
| `ES_JAVA_OPTS` | -Xms768m -Xmx768m | ES 50%·Xms=Xmx. 현 heap 26%사용→과충분 |
| resources | req=limit 1.5Gi/1 | 정본 예산 3×1.5GB, OOM/스왑 방지, **P4 후 락** |
| initContainer sysctl | vm.max_map_count=262144 | ES 필수 커널값(노드 SSH 불필요) |
| secureSettings | es-s3-creds→keystore | 스냅샷 S3 인증 |

## 3. «STS» (ECK가 «CR»에서 생성 — 문서화만)
```
recipes-es-es-zone-a   replicas 1   (호스트 A)
recipes-es-es-zone-b   replicas 2   (호스트 B)   → 합계 파드 3
```
| 속성 | 값 | 근거 |
|---|---|---|
| Kind | **StatefulSet** (Deploy 아님) | 안정 identity·PVC·quorum → Deploy면 파괴 |
| 파드명 | `recipes-es-es-zone-{a,b}-{0..}` | 순서형 안정 이름 |
| PDB | ECK 자동 `maxUnavailable:1` | 드레인/업그레이드가 2/3 quorum 유지 |
| HPA | **없음** | quorum 3 고정. 확장=nodeSet count 수동 |

## 4. «PVC» elasticsearch-data (volumeClaimTemplate → 파드당 1)
```
elasticsearch-data-recipes-es-es-zone-a-0
elasticsearch-data-recipes-es-es-zone-b-0
elasticsearch-data-recipes-es-es-zone-b-1
```
| 필드 | 값 | 근거 |
|---|---|---|
| accessModes | **ReadWriteOnce** | ES는 블록스토리지 전용. RWX 금지(정본 전볼륨 RWO) |
| storageClassName | `openebs-lvm` (EKS=gp3) | 하드코딩 금지, 오버레이 변수(§5.3) |
| storage | **5Gi** | 실데이터 5.9MB + 머지2×·translog·성장 여유 |
| volumeBindingMode | WaitForFirstConsumer | 노드 고정 후 바인딩 |

## 5. «SVC» (ECK 자동 2종)
```yaml
recipes-es-es-http       type: ClusterIP   port: 9200 (HTTPS)   # 앱 질의
recipes-es-es-transport  clusterIP: None   port: 9300           # 노드간 discovery
```
| 서비스 | 용도 | 소비자 | 근거 |
|---|---|---|---|
| es-http | 검색 질의 | 챗·레시피·인덱서·exporter | 앱 `eshost`가 이 DNS |
| es-transport | 클러스터링 | ES 노드끼리 | Headless=파드 직접 discovery |

## 6. «Secret»
| 이름 | 생성 | 내용 | 근거 |
|---|---|---|---|
| `recipes-es-es-elastic-user` | ECK 자동 | `elastic` 계정 비번 | 결정3 인증 |
| `recipes-es-es-http-certs-public` | ECK 자동 | HTTP CA 인증서 | 앱 TLS 검증 |
| `recipes-es-es-transport-certs` | ECK 자동 | 노드간 mTLS | 내부 암호화 |
| `es-s3-creds` | **ESO 주입** | s3.client.default.access_key/secret_key | 스냅샷 repo 인증(→CR secureSettings) |
| (앱측) `es-app-creds` | **ESO(ExternalSecret)** | ES 유저/비번→챗·레시피·인덱서 ns | 정본§6.4 ESO |

## 7. «NP» NetworkPolicy `es-ingress-9200` (표준·이식용)
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: es-ingress-9200, namespace: data }
spec:
  podSelector: { matchLabels: { elasticsearch.k8s.elastic.co/cluster-name: recipes-es } }
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector: { matchLabels: { app: chat } }
        - podSelector: { matchLabels: { app: recipe } }
        - podSelector: { matchLabels: { app: es-indexer } }
        - podSelector: { matchLabels: { app: pgsync } }
      ports: [{ port: 9200, protocol: TCP }]
```
- **근거**: 9200을 **허용 목록만** 접근(정본§6.1). 표준 NP라 EKS 이식 100% 보존.

## 8. «CNP» CiliumNetworkPolicy `es-cilium` (실제 강제·Cilium 네이티브)
```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata: { name: es-cilium, namespace: data }
spec:
  endpointSelector: { matchLabels: { elasticsearch.k8s.elastic.co/cluster-name: recipes-es } }
  ingress:                          # 앱 파드 → 9200 (L3/4)
    - fromEndpoints: [{ matchLabels: { app: chat } }, { app: recipe }, { app: es-indexer }, { app: pgsync }]
      toPorts: [{ ports: [{ port: "9200", protocol: TCP }] }]
  egress:
    - toEndpoints: [{ matchLabels: { "k8s:io.kubernetes.pod.namespace": kube-system, "k8s-app": kube-dns } }]
      toPorts: [{ ports: [{ port: "53", protocol: UDP }] }]        # CoreDNS 예외 필수
    - toFQDNs: [{ matchName: "s3.ap-northeast-2.amazonaws.com" }]   # 스냅샷 S3 아웃바운드
      toPorts: [{ ports: [{ port: "443", protocol: TCP }] }]
```
| 규칙 | 값 | 근거 |
|---|---|---|
| ingress 9200 | 앱 4종만 | 정본§6.1 실제 강제(Cilium) |
| egress DNS | CoreDNS(53) | default-deny 시 누락하면 클러스터 마비(§6.1 함정) |
| egress FQDN | s3…amazonaws.com:443 | ES→S3 스냅샷 아웃바운드(§6.3) |
- **NP vs CNP**: NP=이식용 표준자산, CNP=Cilium 실제 강제(+FQDN egress). 둘 병행(정본 패턴).

## 9. «Job» (컷오버 1회성 2종)
### 9-1. `es-index-template` (재색인 前, ArgoCD PostSync)
```yaml
apiVersion: batch/v1
kind: Job
metadata: { name: es-index-template, namespace: data }
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: apply
          image: curlimages/curl
          env: [{ name: ES_PW, valueFrom: { secretKeyRef: { name: recipes-es-es-elastic-user, key: elastic } } }]
          command: ['sh','-c']
          args:
            - >
              curl -sk -u elastic:$ES_PW -XPUT https://recipes-es-es-http:9200/_index_template/recipes
              -H 'Content-Type: application/json' -d @/tmpl/recipes.json
      volumes: [{ name: tmpl, configMap: { name: es-recipes-template } }]
```
**템플릿 내용(`recipes.json`)** — 결정1 산출물:
```jsonc
{ "index_patterns": ["recipes","recipes_v*"],
  "template": {
    "settings": {
      "number_of_shards": 1, "number_of_replicas": 1,
      "analysis": { "tokenizer": { "nori_mixed": { "type":"nori_tokenizer","decompound_mode":"mixed" } },
        "analyzer": { "korean": { "type":"custom","tokenizer":"nori_mixed","filter":["nori_readingform","lowercase"] } } } },
    "mappings": { "properties": {
      "recipe_id":{"type":"long"}, "name":{"type":"text","analyzer":"korean"},
      "category":{"type":"keyword"}, "cook_method":{"type":"keyword"}, "cooking_time":{"type":"keyword"},
      "level_nm":{"type":"keyword"}, "serving":{"type":"keyword"},
      "kcal":{"type":"float"}, "carb_g":{"type":"float"}, "protein_g":{"type":"float"}, "fat_g":{"type":"float"},
      "ingredient_names":{"type":"text","analyzer":"korean"}, "ingredient_item_ids":{"type":"keyword"},
      "servable":{"type":"boolean"}, "source":{"type":"keyword"}, "image_url":{"type":"keyword","index":false} } } } }
```
| 필드 | 값 | 근거 |
|---|---|---|
| shards/replicas | 1 / 1 | 6MB→단일샤드 최적 + HA(하드코딩 0 대체) |
| korean 분석기 | 현행 1:1 | nori 형태소 |
| 매핑 | 현행 recipes 1:1 | 챗 `multi_match`/`terms` 의존 shape 보존 |

### 9-2. `es-reindex-recipes` (컷오버 재색인)
```yaml
apiVersion: batch/v1
kind: Job
metadata: { name: es-reindex-recipes, namespace: data }
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: reindex
          image: harbor.local/pipelines/ingest:latest   # index_recipes_es.py 포함
          command: ['python','index_recipes_es.py']
          env:
            - { name: ESHOST, value: "recipes-es-es-http:9200" }
            - { name: ES_PW, valueFrom: { secretKeyRef: { name: recipes-es-es-elastic-user, key: elastic } } }
            - { name: PGHOST, value: "pg-rw.data" }
```
| 속성 | 값 | 근거 |
|---|---|---|
| Kind | **Job**(1회) | 컷오버 1회성 → CronJob 아님 |
| 로직 | 품질게이트 그대로 | source='10K'+미매칭0 |
| **SETTINGS** | **제거** | 설정은 템플릿(9-1) 소유(결정1) |

---

## 컷오버 순서 (오브젝트 적용 순)
```
① ECK 번들(«CRD»+오퍼레이터STS) → ② «CR» recipes-es(→«STS»2·«PVC»3·«SVC»2·«Secret») 
→ ③ «Secret» es-s3-creds·앱creds(ESO) → ④ «Job» es-index-template → ⑤ «Job» es-reindex-recipes 
→ ⑥ «NP»+«CNP» 적용 → ⑦ 검증(green·nori·replica 호스트교차) → ⑧ 앱 eshost 스위치 → ⑨ 구 ES 폐기
```

## 인프라 협의 3건
1. 토폴로지 라벨 → `node.attr.host` awareness 노출(신규부담 0)
2. nori bake 이미지 레지스트리 경로(Harbor→ECR)
3. «Job»(템플릿/재색인) 소유 위치(AI 레포 vs config 레포) + ArgoCD PostSync 훅

---

## 설정 근거 — 한 문장 설명 (팀 공유용)

**«CRD» Elasticsearch**
- ECK를 설치하면 자동으로 생기는 '설정 양식'이라, 이게 있어야 우리가 쓴 ES 설정을 쿠버네티스가 알아듣습니다.

**«CR» recipes-es (설계 본체)**
- **nori 이미지**: 한국어 형태소 분석기(nori)를 기본 이미지에 미리 구워 넣어야 레시피가 한국어로 제대로 검색됩니다.
- **버전 8.15.3 고정**: 지금 쓰는 버전과 똑같이 못 박아야 플러그인·매핑이 어긋나지 않습니다.
- **노드 A에 1·B에 2**: ES를 3대로 띄우되 물리서버를 갈라 배치해, 한쪽 서버가 통째로 죽어도 데이터가 살아있게 합니다.
- **host 딱지 + awareness**: 각 ES에 'A서버/B서버' 딱지를 붙여 원본과 복제본이 같은 물리서버에 몰리는 걸 막습니다(안 그러면 그 서버가 죽을 때 둘 다 날아갑니다).
- **힙 768m**: ES가 쓸 메모리를 파드의 절반만 주고 나머지 절반은 검색속도를 좌우하는 캐시로 남기며, 지금 실사용이 그보다 훨씬 적어 넉넉합니다.
- **메모리 1.5Gi 고정(요청=상한)**: 인프라가 정한 ES 몫을 최소=최대로 똑같이 잡아 메모리가 갑자기 모자라 죽는 일을 막습니다.
- **initContainer(sysctl)**: ES는 켜지기 전 리눅스 커널값 하나를 꼭 바꿔야 하는데, 파드가 시작할 때 이걸 자동으로 해줍니다.
- **secureSettings(S3 키)**: 백업을 S3에 보낼 때 쓸 열쇠를 ES 금고에 안전하게 넣어둡니다.

**«STS» ES 노드**
- **StatefulSet 사용**: ES는 각자 고유 이름과 자기 디스크를 계속 유지해야 해서, 아무 파드나 갈아끼우는 Deployment가 아니라 StatefulSet으로 띄웁니다.
- **PDB(동시 1대만)**: 업그레이드·점검으로 여러 대가 한꺼번에 꺼지면 정족수가 깨지므로, 동시에 1대까지만 꺼지게 막아둡니다.
- **HPA 없음**: ES는 3대 정족수가 정해져 있어 자동으로 대수를 늘렸다 줄였다 하면 안 되므로 오토스케일을 붙이지 않습니다.

**«PVC» 데이터 볼륨**
- **RWO(단독 점유)**: ES 디스크는 한 파드만 붙잡는 방식이라야 하며, 이게 클라우드 디스크와도 똑같아 나중에 AWS로 옮겨도 그대로 갑니다.
- **storageClass 변수화**: 온프렘은 로컬 SSD, AWS는 gp3를 쓰도록 이름만 바꾸면 되게 빼둡니다.
- **5Gi**: 실제 데이터는 6MB로 작지만, 검색엔진이 내부 정리 때 잠깐 2배 공간을 쓰고 앞으로 늘 여유까지 감안해 5GB로 잡습니다.

**«SVC» 서비스**
- **es-http(9200)**: 앱들이 검색 요청을 보내는 대표 주소이고, 앱은 이 이름 하나만 바라봅니다.
- **es-transport(9300, headless)**: ES 3대가 서로를 찾아 한 무리를 이루기 위한 내부 전용 통로입니다.

**«Secret» 자격증명·인증서**
- **elastic-user**: ES 로그인 비밀번호를 ECK가 자동으로 만들어 보관합니다.
- **http-certs**: 앱이 '이 ES가 진짜인지' 확인(TLS)할 때 쓰는 인증서입니다.
- **transport-certs**: ES끼리 주고받는 통신을 암호화하는 인증서입니다.
- **es-s3-creds / 앱 creds (ESO)**: 백업용 S3 열쇠와 앱의 ES 로그인 계정을 외부 비밀저장소에서 자동으로 가져와 넣어줍니다.

**«NP» 표준 방화벽**
- ES에 접근 가능한 앱을 챗·레시피·인덱서·pgsync 넷으로만 제한하는 표준 규칙이며, 나중에 AWS로 옮겨도 그대로 씁니다.

**«CNP» Cilium 방화벽**
- **ingress 제한**: 위 방화벽을 우리가 실제로 쓰는 네트워크(Cilium)가 강제하는 버전입니다.
- **DNS 열기**: 차단을 켜면 이름 조회(DNS)까지 막혀 클러스터가 먹통이 되므로 DNS는 반드시 열어둡니다.
- **S3만 열기**: ES가 백업을 보낼 S3 주소로 나가는 것만 콕 집어 허용합니다.
- **NP+CNP 둘 다**: 표준규칙(NP)은 이사용 자산으로, Cilium규칙(CNP)은 지금 실제로 막는 용도로 함께 둡니다.

**«Job» 일회성 작업**
- **인덱스 템플릿 등록**: 레시피를 담기 전에 샤드 수·복제본 수·한국어 분석기·필드 형식을 미리 정해두는 '틀'을 한 번 등록합니다.
- **샤드 1개**: 데이터가 작아 여러 조각으로 쪼개면 검색 정확도만 나빠지므로 1개로 둡니다.
- **복제본 1벌**: 원본 외에 사본 1벌을 둬서 한 대가 죽어도 검색이 안 끊기게 합니다.
- **매핑 그대로 보존**: 지금 챗이 검색에 쓰는 필드 형식을 똑같이 옮겨야 검색이 깨지지 않습니다.
- **재색인 Job**: 레시피를 원본 DB(PG)에서 새 ES로 다시 채우는 일회성 작업이며, DB에서 언제든 다시 만들 수 있어 안전합니다.
- **스크립트에서 설정 제거**: 예전엔 이 스크립트가 설정을 직접 갖고 있어 환경이 바뀌면 어긋났는데, 이제 설정은 위 '틀(템플릿)'이 맡고 스크립트는 데이터만 넣습니다.
