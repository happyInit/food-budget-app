# PGSync 이미지 — 공식 `toluaina1/pgsync` 를 안 쓰고 PyPI 에서 자체 빌드한다.
#
# ── 왜 자체 빌드인가 (2026-08-10 재확인 — 구 사유는 절반이 낡았다) ─────────────────────────
# 구 주석은 "공식 이미지는 arm64 전용이라 x86_64(.8)에서 못 씀"이었다. `.8` VM 은 P4(2026-07-31)에서
# 파괴됐고 AWS 프로덕션은 Graviton(arm64)이라 그 문장만 보면 전제가 뒤집힌 것처럼 읽힌다. 실측하면:
#   ① 공식 이미지는 **여전히 arm64 단일 플랫폼**이다 — Docker Hub 매니페스트 실측(2026-08-10):
#      `toluaina1/pgsync:latest` = OCI image index, 플랫폼 linux/arm64 하나(+ attestation).
#      amd64 매니페스트가 없다. 온프렘 노드 5/5 가 amd64 이므로 **DR 사이트에서 못 뜬다.**
#      → 전제는 뒤집히지 않았다. AWS 한쪽에서만 뜨는 이미지는 "한 태그로 양쪽" 요건을 못 채운다.
#   ② 태그가 `latest` **하나뿐**이다(태그 총 1개). 버전 핀이 불가능 = `:X.Y.Z`·`:sha` 핀 정책과 충돌하고,
#      재현 가능한 롤백이 안 된다.
# 우리 빌드는 python:3.12-slim(멀티아키) 위에 PyPI 휠만 얹으므로 두 아키텍처 모두 성립한다 —
# pgsync 7.1.0 의 네이티브 의존(psycopg2-binary · greenlet · SQLAlchemy · grpcio · protobuf 등)은
# aarch64 휠이 전부 존재한다(실측: `docs/mp_multiarch_survey.md §A`).
#
# 🔴 결정 사항 아님 — 위는 사실 정리다. 이미지 교체 여부의 선택지는 survey §B-2 에 있다.
#
# PGSync 7.1.0 = PyPI 최신. 의존이 psycopg2-binary(휠 번들) → gcc/libpq-dev 등 빌드툴 불필요.
FROM python:3.12-slim

RUN pip install --no-cache-dir pgsync==7.1.0

# 플러그인 로딩: PGSync 는 'plugins' 패키지를 walk → /app 을 PYTHONPATH 에 둬야
# 런타임 마운트된 /app/plugins(=`plugins` 패키지)를 import 할 수 있다.
WORKDIR /app
ENV PYTHONPATH=/app

# schema.json · plugins/ 는 compose 볼륨으로 /app 에 마운트(이미지에 COPY 안 함).
ENTRYPOINT ["pgsync"]
