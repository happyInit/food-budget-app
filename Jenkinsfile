// mealplanning 모노레포 CI — GitHub Actions build-push-app.yml 포팅 + SonarQube(측정) 추가.
//   바뀐 서비스만 감지 → 각각: Sonar(측정·비차단·main 한정) → 이미지 빌드 → Trivy 게이트(차단) → Harbor push.
//   CD(manifest → ArgoCD)는 클러스터 확보 후. 여기서 CI 는 Harbor push 로 끝.
//
// ⚠️ 컨테이너화된 Jenkins(호스트 docker.sock):
//   - docker build 는 CLI 가 컨텍스트를 스트리밍하므로 그대로 동작.
//   - 소스가 필요한 컨테이너(sonar)는 `--volumes-from jenkins` 로 워크스페이스 볼륨을 물려받아 접근.
//
// 이미지 네이밍 = mealplanning/mp-<서비스>-service (design.md §1.5).
// 태그 = :<sha> + :latest, 릴리스 런(RELEASE_VERSION 지정)은 + :X.Y.Z (3태그 정책 완성).
//   앱·파이프라인·pgsync 는 별개 버전 트랙 — 릴리스는 SERVICES 로 한 트랙만 지정(all·변경감지 금지).
//   앱 트랙 베이스라인 = 1.1.9 (2026-07-27 신 Harbor 수동 push. 파이프라인 트랙 1.1.10 과 무관).

// 서비스 카탈로그 (build-push-app.yml 과 동일 매핑)
//   src     = 변경감지 + Sonar 분석 + pytest 디렉토리
//   context = docker build 컨텍스트 (chat·recipe 는 공유코드 COPY 때문에 레포 루트)
//   test    = pytest 게이트 대상. DB-free 확인된 10개만 true.
//             chat·recipe = 레포루트 vendor 코드 경로 확인 후 추가(후속) · frontend = 파이썬 아님.
//   reqs    = pip 에 넘길 requirements 파일 경로. 키 없으면 'requirements.txt' 기본, '' 이면 -r 플래그 생략.
//   cov     = --cov= 대상. 키 없으면 'app' 기본.
//   crawler-kurly 는 reqs:'' (requirements.txt 없음 — 이중 진실 회피) · cov:'.':
//             가드 테스트가 playwright 를 스텁으로 갈아끼워 런타임 의존성 0 → requirements.txt 를
//             만들지 않아도 pytest·pytest-cov 만으로 돈다(Dockerfile 인라인 핀과 이중 진실이 없다).
def CATALOG = [
  [name:'account',    src:'services/account',    context:'services/account',    dockerfile:'services/account/Dockerfile',    image:'mp-account-service',    test:true],
  [name:'pantry',     src:'services/pantry',     context:'services/pantry',     dockerfile:'services/pantry/Dockerfile',     image:'mp-pantry-service',     test:true],
  [name:'price',      src:'services/price',      context:'services/price',      dockerfile:'services/price/Dockerfile',      image:'mp-price-service',      test:true],
  [name:'recipebook', src:'services/recipebook', context:'services/recipebook', dockerfile:'services/recipebook/Dockerfile', image:'mp-recipebook-service', test:true],
  [name:'mealplan',   src:'services/mealplan',   context:'services/mealplan',   dockerfile:'services/mealplan/Dockerfile',   image:'mp-mealplan-service',   test:true],
  [name:'notify',     src:'services/notify',     context:'services/notify',     dockerfile:'services/notify/Dockerfile',     image:'mp-notify-service',     test:true],
  [name:'ocr',        src:'services/ocr',        context:'services/ocr',        dockerfile:'services/ocr/Dockerfile',        image:'mp-ocr-service',        test:true],
  [name:'operations', src:'services/operations', context:'services/operations', dockerfile:'services/operations/Dockerfile', image:'mp-operations-service', test:true],
  [name:'chat',       src:'services/chat',       context:'.',                   dockerfile:'services/chat/Dockerfile',       image:'mp-chat-service'],
  [name:'recipe',     src:'services/recipe',     context:'.',                   dockerfile:'services/recipe/Dockerfile',     image:'mp-recipe-service'],
  //   video = 영상→레시피 추출(#11). 🔴 **카탈로그에 없어서 이미지가 한 번도 빌드된 적이 없었다**
  //   (Harbor: mealplanning/mp-video-service → NOT_FOUND, 2026-07-30). 그래서 K8s 에 워크로드가
  //   없고 프론트 YoutubeExtract 가 /api/recipes/extract 에서 404 를 받는다. 코드·테스트는 완료 상태.
  //   context='.' — chat·recipe 와 같은 이유(ml/video-recipe 추출·검증 로직 원본을 COPY, 이중화 금지).
  //   srcs 에 ml/video-recipe/ 를 넣는 이유: 로직만 고치면 services/video/ 는 그대로인데 이미지는
  //   갱신돼야 한다(data-pipeline 의 "SQL만 바뀌면 영원히 리빌드 안 됨" 과 같은 함정).
  //   test:true — 로컬 실측으로 DB·Redis 없이 22 passed 확인(services/video/tests).
  [name:'video',      src:'services/video',      srcs:['services/video/','ml/video-recipe/'],
                      context:'.',                   dockerfile:'services/video/Dockerfile',      image:'mp-video-service',      test:true],
  [name:'frontend',   src:'frontend',            context:'frontend',            dockerfile:'frontend/Dockerfile',            image:'mp-frontend'],
  // ── 앱 서비스 외 이미지 (K8s 단계별 필요: pgsync=P1 · ranking=P2 · 파이프라인 2종=P3) ──
  //   구 CI 승계: ranking-serving=build-push-app 매트릭스 · data-pipeline/crawler-kurly=build-push-pipeline paths.
  //   data-pipeline 의 srcs/extra = 루트 Dockerfile 의 COPY 목록 그대로(스키마 SQL 포함 — 2026-07-23
  //   "SQL만 바뀌면 이미지가 영원히 리빌드 안 됨" 확인 건). pytest 게이트는 후속(DB-free 여부 미확인).
  //   pgsync = 종전 .8 로컬 빌드(fb-pgsync:7.1.0)의 Harbor 승격 — 릴리스 버전은 업스트림 pgsync 를 따른다(7.x.y).
  [name:'ranking-serving', src:'ml/recipe-ranking', context:'ml/recipe-ranking', dockerfile:'ml/recipe-ranking/Dockerfile', image:'mp-ranking-serving'],
  [name:'data-pipeline',   srcs:['Dockerfile','pipelines/','crawler/','ml/chat-insights/'], extra:/docs\/prd\/[^\/]+\.sql/,
                           src:'pipelines',         context:'.',               dockerfile:'Dockerfile',                    image:'mp-data-pipeline'],
  //   🔴 crawler-kurly 의 srcs — Dockerfile 이 pipelines/stream/ 에서 4개 파일(_kafka·_topics·
  //      _observability·_delivery)을 COPY 하는데 감지 경로가 crawler/kurly/ 뿐이라, 공유코드를
  //      고쳐도 이 이미지는 리빌드되지 않았다. 파일 4개가 아니라 디렉터리 전체를 넣는다 —
  //      그 의존이 늘 때 또 같은 함정에 빠지지 않게. 대신 pipelines/stream/ 의 아무 파일이나
  //      바뀌면 크롤러도 리빌드되는 비용을 받는다(하루 1회 도는 잡이라 값싸다).
  //      C-44 로 pipelines/transport/ 도 같은 처지가 됐다(Dockerfile 이 _s3.py 를 COPY 한다) → 함께 넣는다.
  [name:'crawler-kurly',   src:'crawler/kurly',     srcs:['crawler/kurly/','pipelines/stream/','pipelines/transport/'],
                           context:'.',             dockerfile:'crawler/kurly/Dockerfile',      image:'mp-crawler-kurly',
                           test:true, reqs:'', cov:'.'],
  [name:'pgsync',          src:'deploy/pgsync',     context:'deploy/pgsync',   dockerfile:'deploy/pgsync/Dockerfile',      image:'mp-pgsync'],
  //   elasticsearch-nori = ECK(P2) 준비물. 공식 ES 에 공식 플러그인 하나를 넣는 재패키징이라 우리 코드가 0줄이고,
  //   그래서 **릴리스 버전 자리에 업스트림 ES 버전을 그대로 쓴다**(infra 트랙 — 런북 Q5).
  //   자체 semver 를 붙이면 "8.19.19 가 든 1.0.0" 같은 이중 버전이 생겨 매핑표가 필요해진다.
  [name:'elasticsearch-nori', src:'infra/images/elasticsearch-nori', context:'infra/images/elasticsearch-nori',
                           dockerfile:'infra/images/elasticsearch-nori/Dockerfile', image:'mp-elasticsearch-nori'],
  //   rollouts-gatewayapi-plugin = Argo Rollouts 트래픽라우터 플러그인 vendoring(ADR-0001 §6.2). nori 와 같은
  //   재패키징(우리 코드 0줄)이라 **업스트림 플러그인 버전**을 릴리스 자리에 쓴다(0.16.0). infra 트랙.
  //   🔴 이 이미지가 없으면 Rollouts 컨트롤러가 기동하지 않는다 = account·recipe 배포 게이트 정지.
  [name:'rollouts-gatewayapi-plugin', src:'infra/images/rollouts-gatewayapi-plugin', context:'infra/images/rollouts-gatewayapi-plugin',
                           dockerfile:'infra/images/rollouts-gatewayapi-plugin/Dockerfile', image:'mp-rollouts-gatewayapi-plugin'],
]

// ── SonarQube 스캐너 공통 설정 ────────────────────────────────────────────────
// 🔴 이 제외 목록이 없으면 품질 게이트가 **구조적으로 통과 불가능**하다(2026-08-03 실측):
//   ① 테스트 코드가 운영 소스로 잡힌다. coverage.xml 은 `--cov=app` 이라 tests/ 를 안 덮는데,
//      Sonar 는 그 파일들의 실행가능 라인을 "커버 대상"으로 세고 전부 미커버 처리한다.
//      account 실측: 운영코드만 보면 83.5%(480줄 중 79줄 미커버)인데, tests/ 258줄이 통째로
//      0% 로 얹혀 **54.3%** 가 됐다. 게이트 임계 80% 를 이것 때문에 못 넘었다.
//   ② pytest 가 워크스페이스에 남기는 coverage.xml 은 **생성물**인데 `sources=.` 이 XML 소스로
//      빨아들였다. account ncloc 1462줄 중 546줄(37%)이 이 파일이었고, 매 빌드 내용이 바뀌니
//      549줄이 매번 "새 코드"로 계상됐다.
//   테스트를 `sonar.tests` 로 승격하지 않고 제외만 하는 이유 = 같은 파일이 sources 와 tests 에
//   동시에 잡히면 인덱싱 에러가 나는데, 이 설정은 사전 드라이런이 어렵다(스캐너+서버 필요).
//   제외만으로 커버리지 분모 문제는 완전히 해소되므로 위험한 쪽을 택하지 않는다.
def SONAR_TEST_PATTERNS = '**/tests/**,**/test_*.py,**/conftest.py,**/*.test.ts,**/*.test.tsx'
def SONAR_EXCLUSIONS    = "coverage.xml,**/__pycache__/**,**/.pytest_cache/**,**/node_modules/**,${SONAR_TEST_PATTERNS}"

// 버전 트랙 별칭 (릴리스 런에서 한 트랙 완전세트 지정용 — 부분 버전세트 landmine 회피)
def TRACKS = [
  'app'     : ['account','pantry','price','recipebook','mealplan','notify','ocr','chat','recipe','video','frontend','ranking-serving','operations'],
  'pipeline': ['data-pipeline','crawler-kurly'],
  // pgsync·elasticsearch-nori·rollouts-gatewayapi-plugin 은 자체 트랙 — SERVICES=<name> 으로 단독 릴리스
  //   (셋 다 업스트림 버전을 따라가므로 앱/파이프라인 트랙과 버전을 맞출 이유가 없다)
]

pipeline {
  agent any

  parameters {
    string(name: 'SERVICES', defaultValue: '',
           description: '빌드할 서비스(콤마구분). 비우면 변경 감지. all=전체 · app/pipeline=트랙 별칭. 예: account / account,pantry / all / pipeline')
    string(name: 'RELEASE_VERSION', defaultValue: '',
           description: '릴리스 버전 태그(X.Y.Z). 지정 시 :sha·:latest 에 더해 :X.Y.Z 를 push. SERVICES 명시 필수(all·변경감지 불가 — 트랙별 버전 독립). 예: SERVICES=pipeline + 1.1.11')
  }

  environment {
    REGISTRY = '192.168.0.10'
    PROJECT  = 'mealplanning'
    TRIVY    = 'aquasec/trivy:0.72.0'
    // 빌드별 docker 크레덴셜 격리 — 공유 ~/.docker/config.json 를 쓰면 한 빌드의
    //   post 'docker logout' 이 다른 빌드의 로그인 세션을 지워, 그 사이 push 가
    //   "no basic auth credentials" 로 실패한다(신규 이미지·다중 브랜치 동시 빌드 시 산발적).
    //   options.disableConcurrentBuilds() 는 동일 브랜치만 막고 Multibranch 의 교차-브랜치
    //   동시성은 못 막아 레이스가 남는다 → config 를 워크스페이스로 격리해 근본 차단.
    DOCKER_CONFIG = "${WORKSPACE}/.docker"
    AWSCLI       = 'amazon/aws-cli:latest'   // 릴리스 이미지 S3 백업 업로더 (컨테이너 — Jenkins 호스트에 aws 불요)
    IMAGE_BACKUP = 'mp-image-backup-ap2'     // 릴리스 이미지 백업 버킷
  }

  options {
    timestamps()
    disableConcurrentBuilds()
    // 빌드 이력 상한 — Multibranch 는 브랜치·PR 마다 builds/ 가 따로 쌓인다.
    //   PR 회전이 하루 4개 수준이라 상한이 없으면 로그·기록이 단조 증가한다.
    buildDiscarder(logRotator(numToKeepStr: '20', artifactNumToKeepStr: '5'))
  }

  // triggers 블록 제거 — Multibranch 는 Branch Source scan 웹훅(ci.mealbong.cloud → /github-webhook/)으로 빌드한다.
  //   pipeline triggers.githubPush() 는 단일 Pipeline job 시절 것 — Multibranch 에선 불필요·중복(#389 STEP3 컷오버, 2026-07-30).

  stages {
    stage('빌드 대상 결정') {
      steps {
        script {
          // 릴리스 가드 — 버전 태그는 명시적 대상만 (변경감지·all 금지).
          //   앱·파이프라인·pgsync 는 별개 버전 트랙(CLAUDE.md 3태그 정책)이라 한 릴리스 = 한 트랙.
          //   변경감지에 버전을 얹으면 부분 버전세트(landmine)가 생긴다.
          if (params.RELEASE_VERSION?.trim() &&
              (!params.SERVICES?.trim() || params.SERVICES.trim().equalsIgnoreCase('all'))) {
            error "릴리스 런은 SERVICES 명시 필수 — 트랙 별칭(app/pipeline) 또는 이름 나열. all·변경감지에는 버전 태그를 찍지 않는다."
          }
          def picked
          if (params.SERVICES?.trim()) {
            def raw = params.SERVICES.trim()
            if (raw.equalsIgnoreCase('all')) {
              // 전체 — 새 Harbor 최초 채우기 등
              picked = CATALOG
              echo "전체 빌드: ${picked.collect{it.name}.join(', ')}"
            } else if (TRACKS.containsKey(raw.toLowerCase())) {
              // 트랙 별칭 — 릴리스 런에서 한 트랙 완전세트 지정
              picked = CATALOG.findAll { TRACKS[raw.toLowerCase()].contains(it.name) }
              echo "트랙 '${raw}': ${picked.collect{it.name}.join(', ')}"
            } else {
              // 수동 지정 — 콤마구분 이름
              def want = raw.split(',').collect { it.trim() }
              picked = CATALOG.findAll { want.contains(it.name) }
              echo "수동 지정: ${picked.collect{it.name}.join(', ')}"
            }
          } else {
            // 변경 감지 — PR 이면 merge-base(3점) 기준 전체, 아니면 이전 커밋 대비 (얕은 클론이면 실패 → 빈 목록)
            //   crawler 샘플 산출물(output/)은 제외 — 구 GH paths 의 '!crawler/**/output/**' 승계.
            //   🔴 #389 위험2: PR 을 HEAD~1 로 보면 마지막 1커밋만 감지 → 커밋 여러 개면 검증 누락. CHANGE_TARGET 3점으로 전체.
            //   ⚠️ 3점 diff 는 non-shallow 클론 전제(Multibranch 컷오버 시 shallow 해제 필요 — #389 STEP3).
            def range   = env.CHANGE_TARGET ? "origin/${env.CHANGE_TARGET}...HEAD" : "HEAD~1..HEAD"
            def changed = sh(script: "git diff --name-only ${range} 2>/dev/null || true", returnStdout: true).trim()
            def lines = (changed ? changed.readLines() : []).findAll { !(it ==~ /crawler\/.*\/output\/.*/) }
            picked = CATALOG.findAll { s ->
              def prefixes = s.srcs ?: [s.src + '/']
              lines.any { l -> prefixes.any { p -> l.startsWith(p) } || (s.extra && l ==~ s.extra) }
            }
            echo "변경 감지: ${picked.collect{it.name}.join(', ') ?: '(없음)'}"
          }
          // 다음 스테이지로 전달
          env.TARGETS = picked.collect { it.name }.join(',')
        }
      }
    }

    stage('빌드·스캔·푸시') {
      when { expression { env.TARGETS?.trim() } }
      steps {
        withCredentials([usernamePassword(credentialsId: 'harbor-cred',
            usernameVariable: 'HARBOR_USER', passwordVariable: 'HARBOR_PASS')]) {
          script {
            def sha      = env.GIT_COMMIT
            def registry = env.REGISTRY
            def project  = env.PROJECT
            def trivy    = env.TRIVY
            def names    = env.TARGETS.split(',')
            def targets  = CATALOG.findAll { names.contains(it.name) }

            // Harbor 로그인 (한 번)
            sh 'echo "$HARBOR_PASS" | docker login "$REGISTRY" -u "$HARBOR_USER" --password-stdin'

            def failed = []
            def backupFailed = []   // S3 이미지 백업 실패분 — 빌드는 UNSTABLE 로만 내린다(위 4) 주석)
            for (s in targets) {
              try {
                def img = "${registry}/${project}/${s.image}"
                echo "── ${s.name} → ${img} ──"

                // 1) pytest 게이트 (DB-free 확인 서비스만) — 실패 시 이 서비스 중단(빌드·push 안 함).
                //    coverage.xml 을 남겨 Sonar 가 커버리지로 읽는다. vendor 코드용 PYTHONPATH 에 레포루트 포함.
                //    httpx = fastapi.testclient(TestClient) 의 런타임 의존성 — 테스트 전용이라 여기서만 설치
                //    (런타임 requirements.txt 엔 미포함). 없으면 TestClient 쓰는 테스트가 RuntimeError 로 죽는다.
                if (s.test) {
                  def reqs = (s.reqs != null) ? s.reqs : 'requirements.txt'
                  def cov  = s.cov ?: 'app'
                  // reqs:'' 이면 requirements.txt 가 없다(crawler-kurly) → -r 플래그 자체를 생략.
                  //   빈 문자열과 null 을 구분해야 하므로 Elvis(s.reqs ?:) 는 못 쓴다('' 이 falsy).
                  def install = reqs ? "-r ${reqs} pytest pytest-cov httpx" : "pytest pytest-cov httpx"
                  sh """
                    docker run --rm --volumes-from jenkins -w "\$WORKSPACE/${s.src}" \
                      -e PYTHONPATH="\$WORKSPACE/${s.src}:\$WORKSPACE" \
                      python:3.12-slim \
                      sh -c "pip install --no-cache-dir -q ${install} \
                             && python -m pytest -q --cov=${cov} --cov-report=xml"
                  """
                }

                // 2) Sonar 분석 (측정만 — 실패해도 빌드 계속). 하드 게이트는 Trivy.
                //    🔴 main 에서만 돈다. SonarQube Community 는 **브랜치 분석이 없어서** PR 빌드의
                //       분석이 같은 projectKey 를 그대로 덮어쓴다. 실측(2026-08-03): mp-chat-service
                //       의 최근 분석 리비전이 PR 브랜치 커밋(8e71918 "Merge main into fix/chat-qa")
                //       이었다. 그러면 UI 의 빨강/초록은 main 상태가 아니라 "마지막에 돈 아무 브랜치"
                //       상태가 되고, New Code 기준선까지 PR 쪽으로 끌려간다.
                //    projectVersion 을 붙이는 이유 = 기본 New Code 기준이 PREVIOUS_VERSION 인데
                //       버전을 한 번도 안 넘겨서("not provided") 기준선이 **프로젝트 첫 분석일에
                //       붙박이**였다. account 는 1948줄 중 980줄이 영구히 "새 코드"로 남아 있었다.
                //       main 빌드마다 sha 로 버전이 바뀌면 새 코드 = "지난 main 분석 이후 변경분".
                if (env.BRANCH_NAME == 'main') {
                  try {
                    withSonarQubeEnv('sonarqube') {
                      sh """
                        docker run --rm --volumes-from jenkins -w "\$WORKSPACE/${s.src}" \
                          -e SONAR_HOST_URL="\$SONAR_HOST_URL" -e SONAR_TOKEN="\$SONAR_AUTH_TOKEN" \
                          sonarsource/sonar-scanner-cli \
                            -Dsonar.projectKey=${s.image} \
                            -Dsonar.projectVersion='${params.RELEASE_VERSION?.trim() ?: sha.take(7)}' \
                            -Dsonar.sources=. \
                            -Dsonar.exclusions='${SONAR_EXCLUSIONS}' \
                            -Dsonar.python.coverage.reportPaths=coverage.xml
                      """
                    }
                  } catch (e) {
                    echo "⚠️ Sonar(${s.name}) 스킵(측정 단계라 계속): ${e.message}"
                  }
                } else {
                  echo "Sonar(${s.name}) 스킵 — main 아님(${env.BRANCH_NAME}). Community 는 브랜치 분석이 없어 PR 분석이 main 프로젝트를 덮어쓴다."
                }

                // 3) 빌드 → Trivy 게이트(CRITICAL fixable 이면 실패) → push
                //    릴리스 런이면 :X.Y.Z 불변 태그 추가 (3태그 정책 완성)
                def rel = params.RELEASE_VERSION?.trim()
                sh """
                  docker build -f ${s.dockerfile} -t ${img}:${sha} -t ${img}:latest ${rel ? "-t ${img}:${rel}" : ''} ${s.context}
                  docker run --rm \
                    -v /var/run/docker.sock:/var/run/docker.sock \
                    -v trivy-cache:/root/.cache \
                    ${trivy} image --scanners vuln --severity CRITICAL --ignore-unfixed --exit-code 1 ${img}:${sha}
                  docker push ${img}:${sha}
                  docker push ${img}:latest
                  ${rel ? "docker push ${img}:${rel}" : ':'}
                """

                // 4) 릴리스 이미지 S3 백업 (릴리스 런만).
                //    게이트(pytest·Trivy) 통과 + push 성공 뒤에만 도달. 이미지는 이미 Harbor 에
                //    있으므로 S3 일시오류로 **릴리스를 실패시키지는 않는다**.
                //
                //    🔴 다만 빌드를 UNSTABLE 로 내린다(2026-08-03). 종전엔 echo 만 하고 SUCCESS 라
                //    1.2.0 릴리스가 **전 서비스 백업 실패한 채 초록**이었고 아무도 몰랐다
                //    (credential username 에 입력창 안내문구 "AWS access key ID" 가 그대로 저장돼
                //     InvalidAccessKeyId). "실패해도 릴리스는 계속" 과 "실패를 숨긴다" 는 다르다 —
                //    앞은 의도된 설계고 뒤는 사고였다. UNSTABLE 이면 노랑으로 보이고 알림도 뜬다.
                if (rel) {
                  try {
                    withCredentials([usernamePassword(credentialsId: 'mp-backup-s3',
                        usernameVariable: 'AWS_ACCESS_KEY_ID', passwordVariable: 'AWS_SECRET_ACCESS_KEY')]) {
                      sh """
                        docker save ${img}:${rel} | gzip | docker run --rm -i \
                          -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION=ap-northeast-2 \
                          ${env.AWSCLI} s3 cp - s3://${env.IMAGE_BACKUP}/${s.image}/${rel}.tar.gz
                      """
                    }
                    echo "📦 이미지 백업 → s3://${env.IMAGE_BACKUP}/${s.image}/${rel}.tar.gz"
                  } catch (ae) {
                    backupFailed << "${s.name}:${rel}"
                    unstable("이미지 백업 실패(${s.name}:${rel}) — 릴리스는 계속(이미지는 Harbor 에 있음): ${ae.message}")
                  }
                }
              } catch (e) {
                failed << s.name
                echo "❌ ${s.name} 실패: ${e.message}"
              }
            }
            // 백업 실패는 서비스마다 흩어져 있어 로그 끝에서 한 번 더 모아 보여준다 —
            // 릴리스 런은 로그가 길어 중간의 UNSTABLE 한 줄은 눈에 안 들어온다.
            if (backupFailed) {
              echo "⚠️ S3 이미지 백업 실패 ${backupFailed.size()}건: ${backupFailed.join(', ')}\n" +
                   "   → Jenkins credential 'mp-backup-s3' 를 먼저 확인할 것(2026-08-03 전례).\n" +
                   "   → 이미지 자체는 Harbor 에 있으므로 릴리스는 유효하다. 백업만 다시 올리면 된다."
            }
            if (failed) {
              error "빌드 실패 서비스: ${failed.join(', ')}"
            }
          }
        }
      }
    }

    stage('config 레포 태그 커밋 (CD 인계)') {
      // Harbor push 성공 후 → 빌드된 앱 서비스의 :sha 를 config 레포에 핀 → ArgoCD auto-sync 가 자동 배포.
      //   config 레포엔 앱 워크로드만 오버레이가 있다(data-pipeline·crawler-kurly·pgsync 는 없음 → 스킵).
      //   핀 = :sha(불변, 플랜 §7.3 · :latest 금지). 🔴 credential 'config-repo-deploy-key'(SSH 쓰기키) 선행 필수 —
      //   없으면 이 스테이지가 실패한다(이미 push 는 끝난 상태). 상세 = PR 설명.
      // 🔴 #389 위험1: PR 빌드에서는 CD(config 커밋=배포) 금지. changeRequest()=PR 이면 스킵.
      //   branch 'main' 가드는 Multibranch 컷오버와 함께 추가한다 — 단일 Pipeline 엔 BRANCH_NAME 부재라
      //   먼저 넣으면 이 스테이지가 통째 스킵되어 현재 CD 가 멈춘다(#389 STEP3 에서 반영).
      when {
        allOf {
          branch 'main'                             // #389 STEP3 컷오버 — Multibranch main 빌드만 CD(BRANCH_NAME=main). PR·타브랜치 배포 금지.
          expression { env.TARGETS?.trim() }
          not { changeRequest() }                   // (branch 'main' 이 이미 PR 제외 — 방어적 중복 유지)
        }
      }
      steps {
        withCredentials([sshUserPrivateKey(credentialsId: 'config-repo-deploy-key', keyFileVariable: 'CFG_KEY')]) {
          script {
            def sha       = env.GIT_COMMIT
            def kustomize = 'registry.k8s.io/kustomize/kustomize:v5.4.3'
            def cfgRepo   = 'git@github.com:happyInit/mealplanning-config.git'

            // config 레포 얕은 클론 (쓰기키로)
            sh """
              rm -rf .cfgrepo
              GIT_SSH_COMMAND="ssh -i \$CFG_KEY -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null" \
                git clone --depth 1 ${cfgRepo} .cfgrepo
            """

            // 빌드된 서비스 중 config 오버레이가 있는 것만 newTag=:sha 로 갱신
            //
            // 🔴 A-42 — 사이트 오버레이를 **둘 다** 핀한다(2026-08-13). 종전엔 onprem 하나만 핀해서
            //    main 머지마다 온프렘 태그만 오르고 `overlays/eks` 는 영원히 낡았다
            //    (실측: account eks = `1.1.9`, 나머지 대부분 `d20d3fdb…` — 컷오버 때 옛 이미지가 뜬다).
            //    🟢 C-83 동결에 걸리지 않는다 — 동결 대상은 *형상* 이고 이미지 태그는 CD 가 하는 일이다.
            //    ⚠️ 과도기 조치다. 이관 후 CI 는 GitLab(C-2)이고 그쪽 `config-pin` 잡이 eks 를 맡는다.
            def SITES = ['onprem', 'eks']
            def committed = []   // 커밋 메시지용 (서비스 이름만)
            def detail    = []   // 로그용 name(onprem+eks)
            for (name in env.TARGETS.split(',')) {
              def s = CATALOG.find { it.name == name }
              if (!s) continue
              def img = "${env.REGISTRY}/${env.PROJECT}/${s.image}"
              def pinned = []
              for (site in SITES) {
                def overlay = "services/${name}/overlays/${site}"
                if (sh(script: "test -d .cfgrepo/${overlay} && echo y || echo n", returnStdout: true).trim() != 'y') {
                  continue
                }
                // 🔴 기존 newName 을 **읽어서 그대로 돌려준다.** eks 오버레이의 newName 은 ECR 주소인데
                //    (`PLACEHOLDER.dkr.ecr.ap-northeast-2.amazonaws.com/mp-…`), kustomize v5.4.3 실측상
                //      · `edit set image <name>=<img>:<sha>` → newName 을 **Harbor 주소로 덮어쓴다**
                //      · `edit set image <name>:<sha>`       → newName 을 **통째로 지운다**
                //    둘 다 ECR 매핑을 파괴한다. `<name>=<기존newName>:<sha>` 만 태그만 바꾼다.
                //    onprem 은 newName == Harbor 주소라 이 경로로도 결과가 종전과 동일하다(렌더 무변화).
                // 🔴 매칭 키(`name:`)는 양쪽 오버레이 모두 **Harbor 주소**다 — 그래서 ${img} 를 키로 쓴다.
                //    newName 은 오버레이당 정확히 1개(실측 13/13)라 `grep -m1` 이 모호하지 않다.
                def newName = sh(script: "grep -m1 'newName:' .cfgrepo/${overlay}/kustomization.yaml | awk '{print \$2}' || true",
                                 returnStdout: true).trim()
                if (!newName) { newName = img }   // newName 없는 오버레이 방어(예: cloudflared onprem)
                sh """
                  docker run --rm --volumes-from jenkins --user \$(id -u):\$(id -g) \
                    -w "\$WORKSPACE/.cfgrepo/${overlay}" ${kustomize} \
                    edit set image ${img}=${newName}:${sha}
                """
                pinned << site
              }
              if (pinned) {
                committed << name
                detail    << "${name}(${pinned.join('+')})"
              } else {
                // crawler-kurly·data-pipeline·pgsync 등 — services/<name>/overlays/ 자체가 없다.
                // 그 이미지들은 pipelines/ · platform/pgsync/ 트랙에 **base 인라인**으로 핀돼 있어
                // 이 루프의 대상이 아니다(별건 — PR 설명 참조).
                echo "config 오버레이 없음(스킵 — 앱 워크로드 아님): ${name}"
              }
            }

            // 변경분 커밋·push (동일 :sha 재빌드면 no-op). config 레포는 Jenkins 감시 밖 → CI 루프 없음.
            if (committed) {
              sh """
                cd .cfgrepo
                git config user.email 'ci@mealbong.cloud'
                git config user.name 'mealbong-ci'
                git add -A
                if git diff --cached --quiet; then
                  echo 'config 변경 없음 (동일 :sha 재빌드)'
                else
                  git commit -m 'ci(cd): ${committed.join(',')} to ${sha.take(12)}'
                  GIT_SSH_COMMAND="ssh -i \$CFG_KEY -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null" \
                    git push origin HEAD:main
                  echo '✅ config 레포 push → ArgoCD 자동 배포'
                fi
              """
              echo "config 대상: ${detail.join(', ')} @ ${sha.take(12)}"
            } else {
              echo "config 반영 대상 없음 (앱 워크로드 아님 — 파이프라인/pgsync 등)"
            }
          }
        }
      }
    }
  }

  post {
    always {
      sh 'docker logout $REGISTRY || true'
      // 🔴 chown 이 cleanWs 보다 먼저여야 한다. pytest(:156)·Sonar(:168) 컨테이너는
      //    `--volumes-from jenkins` 로 워크스페이스를 물고 **root 로** 돌기 때문에
      //    __pycache__ · .pytest_cache · coverage.xml 이 root 소유로 남는다.
      //    cleanWs 는 jenkins 유저(uid 1000)로 도니 그걸 못 지우는데,
      //    notFailBuild:true 라 **에러 없이 조용히 실패**하고 워크스페이스가 그대로 쌓인다.
      //    (실측 2026-07-31: workspace 7.9G / jobs 25M — 워크스페이스가 사실상 전부였다.)
      sh 'docker run --rm --volumes-from jenkins alpine chown -R $(id -u):$(id -g) "$WORKSPACE" || true'
      cleanWs(deleteDirs: true, notFailBuild: true)
    }
    success { echo "✅ CI 완료: ${env.TARGETS ?: '(대상 없음)'}" }
  }
}
