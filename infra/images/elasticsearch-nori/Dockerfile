# mp-elasticsearch-nori — ECK 용 ES + 한국어 형태소 분석기(nori)
#
# 왜 커스텀 이미지가 필요한가: ECK 는 파드를 오퍼레이터가 만들기 때문에 "기동 후 플러그인 설치"
# 같은 절차를 끼울 자리가 없다. 플러그인이 이미 들어간 이미지를 줘야 한다.
# (현행 VM 도 같은 이유로 로컬 빌드 `fb-elasticsearch-nori:8.15.3` 을 쓰고 있었다 — 이 파일은
#  그 관행을 IaC 로 들이면서 신 네이밍(`mp-`)과 Harbor 로 옮기는 것이다.)
#
# 🔴 베이스는 **docker.elastic.co** 공식 배포본이다. Docker Hub 의 `library/elasticsearch` 가
#    아니다 — ECK 는 elastic 공식 이미지를 전제로 버전·라이선스를 검사한다.
#
# 태깅(런북 Q5, infra 트랙): 3태그 구조는 유지하되 버전 자리에 **업스트림 ES 버전**을 쓴다.
#   우리 코드가 0줄인 재패키징이라 자체 semver 를 붙이면 "8.19.19 가 든 1.0.0" 같은 이중 버전이
#   생긴다. 같은 ES 버전으로 재빌드가 필요하면 `-rN` 리비전을 붙인다.
#   ECK CR 의 image 핀은 정책대로 `:sha`(`spec.version` 이 8.19.19 를 따로 선언한다).
#
# 🔴 ARG 와 실제 태그는 반드시 같이 움직여야 한다 — 다르면 "8.19.19 라 적힌 8.15.3 이미지"가 된다.
ARG ES_VERSION=8.19.19
FROM docker.elastic.co/elasticsearch/elasticsearch:${ES_VERSION}

# analysis-nori = elastic 이 배포하는 공식 플러그인이라 별도 저장소가 필요 없다.
# --batch: 대화형 확인 프롬프트 없이 진행(빌드가 멈추지 않게).
RUN bin/elasticsearch-plugin install --batch analysis-nori

# 빌드 검증 — 플러그인이 실제로 목록에 잡히는지. 실패하면 여기서 빌드가 죽는 게
# 배포 후 "한국어 검색만 조용히 이상한" 상태보다 훨씬 싸다.
RUN bin/elasticsearch-plugin list | grep -q analysis-nori

# 비루트 **고정** (SonarQube S6471). 값을 바꾸는 게 아니다 — 이 베이스는 이미 USER 1000:0
# 으로 뜬다(실측: docker.elastic.co/elasticsearch/elasticsearch:8.19.19 → Config.User=1000:0).
# 명시하는 이유는 두 가지다: ① ES_VERSION 을 올렸을 때 베이스가 USER 를 안 잡으면 조용히
# root 로 떨어지는데 그걸 막는다. ② 스캐너는 베이스 이미지를 못 읽어 이 파일만 보고 판단한다.
#   uid 1000 = elasticsearch, gid 0 = root 그룹 — elastic 공식 이미지의 규약 그대로다
#   (OpenShift 류의 임의 uid 실행을 위해 그룹을 0 으로 둔다). 바꾸지 말 것.
USER 1000:0
