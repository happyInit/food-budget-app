"""env var 컨벤션 — pipelines/ingest/_db.py 의 PG* 이름 재사용."""
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

# ── JWT_SECRET fail-fast (AWS 이관 체크리스트 0-12) — account/app/config.py 복제 ──
# 🔴 커밋된 placeholder 로는 기동하지 않는다. 폴백이 있으면 env 주입이 빠져도 앱은 **정상 기동**하고
#    그 순간부터 "레포만 보면 아는 키"로 토큰을 검증한다 → 토큰 위조가 가능한데 증상이 없다.
#    ⚠️ 이 모듈은 아래에서 전역 `settings = Settings()` 를 만든다 → **import 시점**에 죽는다.
# ⚠️ ConfigError 가 ValueError 를 상속하지 **않는** 이유: pydantic 은 검증 중의 ValueError 를
#    ValidationError 로 감싸면서 입력 dict 전체(PGPASSWORD 포함)를 에러 메시지에 찍는다(실측).
JWT_SECRET_MIN_LEN = 32
JWT_SECRET_PLACEHOLDERS = frozenset({"dev-insecure-change-me", "change-me", "changeme", "secret"})


class ConfigError(RuntimeError):
    """기동을 막는 설정 오류. 🔴 메시지에 비밀 **값**을 넣지 않는다(로그로 샌다)."""


def require_jwt_secret(value: str) -> None:
    """없음·placeholder·과단축 이면 기동을 막는다."""
    s = (value or "").strip()
    if not s:
        raise ConfigError("JWT_SECRET 미주입 — 기본값 폴백을 제거했다(0-12). env/ESO 로 주입하라.")
    if s.lower() in JWT_SECRET_PLACEHOLDERS:
        raise ConfigError("JWT_SECRET 이 개발용 placeholder 다(0-12) — 실제 비밀을 주입하라.")
    if len(s) < JWT_SECRET_MIN_LEN:
        raise ConfigError(
            f"JWT_SECRET 이 너무 짧다({len(s)}자 < {JWT_SECRET_MIN_LEN}자) — HS256 서명키다."
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pghost: str = "localhost"
    pgport: str = "5432"
    pgdatabase: str = "foodbudget"
    pguser: str = "fbapp"
    pgpassword: str = ""

    # 커넥션 풀 (env 튜닝 — 워커 수·PG max_connections와 한 세트로 조정. docs 인프라 핸드오프 참조)
    pg_pool_min: int = 1
    pg_pool_max: int = 5

    # Redis 캐시 — 현재가·핫딜은 읽기 편중이고 가격은 일1~2회만 변경 → 짧은 TTL로 DB 왕복 대폭↓.
    #   무효화 = TTL(크롤 주기보다 훨씬 짧아 staleness 무시 가능) + 크롤 후 refresh 스크립트가 flush.
    redishost: str = "localhost"
    redisport: str = "6379"
    # Sentinel 모드(분기 C — K8s) — 콤마구분 "host:port" 나열, sentinel 파드 3개 전부(단일 DNS 금지).
    # 값이 있으면 db.py 가 Service 대신 Sentinel 로 master 를 찾는다. 비우면 위 단일 호스트 폴백
    # (로컬 개발·단일 Redis 용). 운영은 Sentinel 목록이 주입된다.
    # 근거 = docs/mp_k8s_redis_ha_handoff.md §4(분기 C).
    redis_sentinels: str = ""
    redis_master_group: str = "mymaster"   # 🔴 소문자 — 인라인 sentinel 의 기본 그룹명(CR 로 못 바꿈)
    # 🔴 소켓 타임아웃(체크리스트 `1-15`) — 미설정이면 무한 대기.
    #    AWS 는 사이트 간 지연이 생기는 구성이라 상한이 없으면 그때 드러난다.
    #
    # 🔴 **기본값 = 5.0 = 현행 온프렘 동작**(이슈 #642 · #644 이원화 원칙).
    #    ⚠️ price 만 `requirements.txt` 에 상한이 없어(`redis>=5`) **redis-py 8.x** 를 받는다.
    #       8.0 부터 `socket_timeout` 기본값이 `None` → **5** 로 바뀌었다(실측).
    #       라이브 파드 확인: price=8.1.0(기본 5) · chat=5.3.1(기본 None) · video=5.3.1(기본 None)
    #    ⇒ 여기서 None 을 주면 "5초 → 무한 대기"로 **동작이 나빠진다** — 캐시는 best-effort
    #       우회 경로라 예외가 안 나면 우회로 못 가고 지연이 그대로 응답에 실린다.
    #    그래서 현행과 같은 5.0 을 기본값으로 두고, `overlays/eks` 에서만 3.0 으로 내린다.
    redis_socket_timeout_s: float | None = 5.0           # 5.0 = 현행(redis-py 8 기본) · EKS 는 3.0
    cache_enabled: bool = True
    cache_current_ttl_s: int = 300     # 현재가 캐시 TTL(5분)
    cache_hotdeals_ttl_s: int = 120    # 핫딜 캐시 TTL(2분)
    # ── stale-while-revalidate (2026-08-17) — 근거·실측은 `main.py` 읽기 캐시 절 주석.
    # 만료 뒤에도 옛 값을 내보내는 **유예**. 갱신이 계속 실패해도 이 시간만큼은 조회가 안 끊긴다.
    # 크롤이 하루 1~2회라 10분 지난 딜/현재가는 무해하다 — 신선도보다 가용성을 산다.
    cache_stale_ttl_s: int = 600
    # 갱신 단일비행 락 TTL. 미스 쿼리 실측(1.36초)보다 충분히 길고, 🔴 승자 파드가 죽어도
    # 이 시간이 지나면 풀린다(락이 영구히 남아 갱신이 멈추는 것을 막는 안전장치).
    cache_lock_ttl_s: int = 30
    # 콜드(값이 아예 없음)에서 락을 못 잡은 쪽이 승자의 결과를 기다리는 상한.
    # 넘기면 각자 조회한다 — 느려도 응답은 나가야 하므로 실패로 만들지 않는다.
    cache_cold_wait_s: float = 3.0

    default_limit: int = 20
    history_limit: int = 200
    # 핫딜 조회 상한 — 남용 방지용 가드지, 표시 개수를 정하는 값이 아니다.
    # 유효한 딜은 전부 보여야 하므로 실데이터보다 넉넉해야 한다(실측 2026-08-06: 유효 62건).
    hotdeals_max_limit: int = 500

    # 관심 등록/해제(#29·#30)만 인증이 필요하다 — 조회 API는 지금처럼 공개.
    # 🔴 jwt_secret 은 env 필수 — placeholder 폴백 제거(0-12).
    #    account 서비스와 **같은 값**이어야 발급 토큰을 검증할 수 있다.
    jwt_secret: str = ""
    jwt_alg: str = "HS256"

    def model_post_init(self, _context: Any) -> None:
        require_jwt_secret(self.jwt_secret)


settings = Settings()
