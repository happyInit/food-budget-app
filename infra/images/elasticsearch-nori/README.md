# mp-elasticsearch-nori

ECK(P2 데이터 티어)가 쓸 **ES + nori 커스텀 이미지**. 우리 코드는 0줄이고 공식 배포본에
공식 플러그인 하나를 넣어 재패키징할 뿐이다.

## 버전 올리기

1. `Dockerfile` 의 `ARG ES_VERSION` 수정
2. Jenkins 릴리스 런: `SERVICES=elasticsearch-nori` + `RELEASE_VERSION=<같은 ES 버전>`
3. config 레포의 ECK CR 에서 `spec.version` 과 `image`(`:sha`) 를 함께 갱신

🔴 **셋이 어긋나면 안 된다.** `ARG` ≠ 태그면 "8.19.19 라 적힌 8.15.3", `spec.version` ≠ 이미지면
ECK 가 업그레이드로 오인해 롤링을 돌린다.

## 현재 핀 (2026-07-28 조사)

- ES **8.19.19** — 8.19 는 8.x 최종 라인이고 활발히 패치 중(8.19.19 = 2026-07-21)
- 🔴 **9.x 로 올리지 말 것** — 우리 파이썬 클라이언트 핀이 `elasticsearch[async]>=8.15,<9` 라
  즉시 깨진다. ECK 3.4.1 은 Stack 9 도 지원하므로 `spec.version` 을 느슨하게 두면 사고가 난다
