"""Kafka 전달 실패 관측 — `produce()` 는 **큐에 넣을 뿐**이다 (#558).

## 무엇이 문제였나

`produce()` 는 로컬 큐에 넣고 즉시 돌아온다. 실제 전달 결과는 **delivery report** 로 비동기
통보되는데, 이 레포에는 그걸 받는 콜백(`on_delivery`)이 **한 곳도 없었다.** 그 위에 크롤
프로듀서들은 `flush()` 반환값까지 버려서, 잡은 `produce()` **호출 횟수**를 `record_count` 로
찍고 `result: "success"` 로 마감했다. → **유실을 성공으로 마감한다.**

09037b4(컬리 조용한 절단)와 같은 계열이다. 그때는 "긁다 만 것을 성공으로", 이번은
"보내다 만 것을 성공으로" 보고했다.

## 🔴 `flush()` 확인만으로는 못 잡는다 — 실측 (2026-08-09)

닿지 않는 주소(`127.0.0.1:9`)로 3건 produce · `delivery.timeout.ms=3000`:

    flush remaining = 0     elapsed = 3.0s     ← "다 나갔다"로 읽힌다
    delivery callbacks = 3  전부 _MSG_TIMED_OUT ← 실제로는 3건 전부 영구 실패

(confluent-kafka 2.15.0 / librdkafka 2.15.0)

`flush()` 가 세는 건 **"아직 큐에 남았나"** 다. `delivery.timeout.ms` 만료로 영구 실패한
메시지는 **큐에서 빠지므로** 0 으로 보인다. 그래서 두 겹이 다 필요하다:

    큐에 남음        → flush(timeout) 반환값 > 0        ← 이미 일부 호출부가 잡던 것
    만료로 영구 실패 → on_delivery 콜백                  ← 이 모듈이 새로 잡는 것

## 이 모듈의 경계

- **드라이버 의존이 없다**(`_topics.py` 와 같은 이유). 브로커·confluent_kafka 없이 임포트·검증된다.
- **판정만 한다.** 재시도·백오프·버퍼링은 librdkafka 몫이고, 여기서 하는 일은
  "무엇이 몇 건 실패했는지를 로그와 **종료코드**로 드러내는 것"뿐이다.
- 🔴 **fail-open 을 뒤집지 않는다.** 이미 produce 된 것을 되돌리거나 실행을 막지 않는다.
  부분 데이터가 무데이터보다 낫다 — 다만 **성공으로 보고하지 않는다.**
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

from _observability import get_pipeline_logger

# ── 튜닝 노브 ──────────────────────────────────────────────────────────────────
# 🔴 **librdkafka 기본값(300,000ms)을 그대로 명시**한다. 값을 바꾸는 게 아니라 **보이게** 하는 것이
#    이 PR 의 목적이다. 지금은 브로커가 같은 LAN 이라 5분이 과하지도 부족하지도 않다.
#    AWS 이관 후(크롤러=온프렘 / 브로커=AWS, C-11~C-13)에는 터널 단절 길이에 맞춰 다시 정해야
#    하는데, 그 값은 "터널을 어떻게 건널지"가 정해진 뒤에야 근거를 갖는다 — 그래서 여기서
#    임의로 늘리지 않고 env 로 열어만 둔다.
#    제약: librdkafka 는 delivery.timeout.ms >= linger.ms + request.timeout.ms 를 요구한다
#          (어기면 Producer 생성 시점에 예외 — 조용히 무시되지 않는다).
DELIVERY_TIMEOUT_MS = int(os.environ.get("KAFKA_DELIVERY_TIMEOUT_MS", "300000"))

# flush 대기(초). 종전 크롤 프로듀서는 `flush()` = **무한 대기**였다. 무한이어도 결국
# delivery.timeout.ms 만료로 풀리므로 실질 상한은 어차피 그 값이다 — 다만 명시적 상한이 있어야
# "영원히 안 끝나는 잡" 이 아니라 "실패로 마감한 잡" 이 된다.
# 기본 = delivery.timeout + 30초 여유. 여유가 없으면 아직 재시도 중인 것을 미전달로 오판한다.
FLUSH_TIMEOUT = float(os.environ.get("KAFKA_FLUSH_TIMEOUT", str(DELIVERY_TIMEOUT_MS / 1000 + 30)))

# 실패 로그 표본 상한. 브로커가 통째로 죽으면 실패가 레코드 수만큼(수천 건) 나온다 —
# 전건을 찍으면 로그가 그것만으로 채워져 정작 원인 줄이 밀린다. 표본 + 총계로 대신한다.
LOG_SAMPLE = int(os.environ.get("KAFKA_DELIVERY_LOG_SAMPLE", "5"))


class DeliveryFailed(RuntimeError):
    """전달이 확인되지 않은 메시지가 있다 — 성공으로 마감하면 안 되는 상태."""


def _err_name(err) -> str:
    """KafkaError → 안정적인 짧은 이름. 드라이버 없는 테스트에서도 동작해야 한다."""
    for attr in ("name", "str"):
        fn = getattr(err, attr, None)
        if callable(fn):
            try:
                return str(fn())
            except Exception:      # noqa: BLE001 — 이름 얻기 실패가 관측을 막으면 안 된다
                pass
    return type(err).__name__


class DeliveryTracker:
    """delivery report 를 받아 실패를 센다.

    콜백은 `poll()`/`flush()` 를 호출한 스레드에서 실행된다. 10k 레시피 크롤러는 워커
    스레드에서 produce·poll 하므로 **락이 필요하다**(카운터 증가뿐이라 비용은 무시 가능).

    🔴 **콜백은 절대 예외를 올리지 않는다.** confluent-kafka 는 콜백 예외를 `poll()`/`flush()`
       밖으로 다시 던지는데, 그러면 "관측을 붙였더니 프로듀서가 죽더라"가 된다.
    """

    def __init__(self, component: str = "kafka-producer"):
        self.component = component
        self._lock = threading.Lock()
        self.delivered = 0
        self.failed = 0
        self.errors: dict[str, int] = {}          # {오류명: 건수} — 실패 메시지 기준
        self.broker_errors: dict[str, int] = {}   # {오류명: 건수} — error_cb 기준(연결·fatal)
        self.first_failure: str | None = None
        self.fatal: str | None = None
        self._logged = 0
        self._logger = None

    # ── librdkafka 콜백 ────────────────────────────────────────────────────────
    def on_delivery(self, err, msg) -> None:
        """모든 produce 의 기본 delivery report 콜백(`_kafka.producer()` 가 config 로 등록)."""
        if err is None:
            with self._lock:
                self.delivered += 1
            return
        name = _err_name(err)
        with self._lock:
            self.failed += 1
            self.errors[name] = self.errors.get(name, 0) + 1
            total = self.failed
            if self.first_failure is None:
                self.first_failure = f"{name}: {err}"[:300]
            emit = self._logged < LOG_SAMPLE
            if emit:
                self._logged += 1
        if not emit:
            return
        try:
            topic = msg.topic() if msg is not None else None
            self._log().error(
                "kafka delivery failed",
                extra={
                    "event": "kafka_delivery_failed",
                    "component": self.component,
                    "topic": topic,
                    "result": "failure",
                    "error_code": name,
                    "error_type": "delivery",
                    # _MSG_TIMED_OUT 은 delivery.timeout.ms 만료 = **영구 실패**다.
                    # 재시도 여지가 남아 있으면 애초에 dr 이 오지 않는다.
                    "retryable": False,
                    "failed_count": total,
                },
            )
        except Exception:          # noqa: BLE001 — 로깅 실패가 프로듀서를 죽이면 안 된다
            pass

    def on_error(self, err) -> None:
        """librdkafka `error_cb` — 연결 단절·fatal 상태. 메시지 단위가 아니라 클라이언트 단위다.

        🔴 시끄럽다. 실측(2026-08-09): 브로커 부재 3초에 `_TRANSPORT`·`_ALL_BROKERS_DOWN`
           **16회**. 그래서 이름당 첫 1회만 찍고 나머지는 세기만 한다.
        """
        name = _err_name(err)
        fatal = bool(getattr(err, "fatal", lambda: False)())
        with self._lock:
            seen = self.broker_errors.get(name, 0)
            self.broker_errors[name] = seen + 1
            if fatal and self.fatal is None:
                self.fatal = f"{name}: {err}"[:300]
        if seen and not fatal:
            return
        try:
            self._log().error(
                "kafka client error",
                extra={
                    "event": "kafka_client_error",
                    "component": self.component,
                    "result": "failure",
                    "error_code": name,
                    "error_type": "fatal" if fatal else "transport",
                    "retryable": not fatal,
                },
            )
        except Exception:          # noqa: BLE001
            pass

    # ── 조회 ──────────────────────────────────────────────────────────────────
    def snapshot(self) -> tuple[int, int, dict[str, int]]:
        with self._lock:
            return self.delivered, self.failed, dict(self.errors)

    def _log(self):
        # 지연 생성 + 캐시 — get_pipeline_logger 는 부를 때마다 핸들러를 재설치한다.
        if self._logger is None:
            self._logger = get_pipeline_logger(self.component)
        return self._logger


_TRACKER: DeliveryTracker | None = None


def tracker(component: str | None = None) -> DeliveryTracker:
    """프로세스 공용 트래커.

    프로듀서는 프로세스당 1개(폴러=CronJob 단발, 컨슈머=DLQ 발행용 1개)라 전역 하나로 충분하다.
    프로듀서를 여럿 만들어도 **합산**되므로 "이 프로세스가 몇 건 잃었나"라는 질문에는 그대로 답한다.
    """
    global _TRACKER
    if _TRACKER is None:
        _TRACKER = DeliveryTracker(component or os.environ.get("MP_COMPONENT", "kafka-producer"))
    elif component:
        _TRACKER.component = component
    return _TRACKER


def reset_tracker() -> None:
    """테스트 전용 — 프로세스 전역 상태를 지운다."""
    global _TRACKER
    _TRACKER = None


@dataclass(frozen=True)
class DeliveryReport:
    """마감 시점의 전달 판정."""

    delivered: int
    failed: int
    remaining: int
    produced: int | None = None
    errors: dict[str, int] = field(default_factory=dict)

    @property
    def unaccounted(self) -> int:
        """produce 했는데 성공도 실패도 아직 안 온 건수.

        정상이면 0 이다. 0 이 아니면 **`produce()` 호출 수를 성과로 찍던 그 간극**(이슈 ④)이
        실제로 벌어진 것이므로 유실로 센다.
        """
        if self.produced is None:
            return 0
        return max(0, self.produced - self.delivered - self.failed - self.remaining)

    @property
    def lost(self) -> int:
        return self.failed + self.remaining + self.unaccounted

    @property
    def ok(self) -> bool:
        return self.lost == 0

    def summary(self) -> str:
        base = f"전달 {self.delivered:,}"
        if self.produced is not None:
            base = f"전달 {self.delivered:,}/{self.produced:,}"
        if self.ok:
            return base
        parts = [f"실패 {self.failed:,}", f"미전달 {self.remaining:,}"]
        if self.unaccounted:
            parts.append(f"미확인 {self.unaccounted:,}")
        if self.errors:
            parts.append("·".join(f"{k}={v:,}" for k, v in sorted(self.errors.items())))
        return f"{base} · " + " · ".join(parts)

    def extra(self, **kw) -> dict:
        """구조화 로그 extra. 🔴 `_observability._OPTIONAL_FIELDS` 에 없는 키는 **버려진다**."""
        out = {
            "result": "success" if self.ok else "failure",
            "delivered_count": self.delivered,
            "failed_count": self.failed,
            "remaining_count": self.remaining,
        }
        if self.produced is not None:
            out["record_count"] = self.produced
        if self.errors:
            out["error_code"] = "·".join(sorted(self.errors))
        out.update(kw)
        return out

    def emit(self, log, *, component: str, event_ok: str = "kafka_produce_succeeded",
             event_bad: str = "kafka_delivery_failed", **kw) -> int:
        """마감 로그를 남기고 **종료코드(0/1)** 를 돌려준다.

        호출부 관례: `return report.emit(log, component=COMPONENT, source="kurly")`
        """
        extra = self.extra(component=component, **kw)
        if self.ok:
            log.info("kafka delivery confirmed", extra={"event": event_ok, **extra})
            return 0
        log.error(
            f"kafka delivery incomplete — {self.summary()}",
            extra={"event": event_bad, "reason": "delivery_unconfirmed", **extra},
        )
        return 1


def finalize(producer, *, produced: int | None = None, timeout: float | None = None,
             trk: DeliveryTracker | None = None) -> DeliveryReport:
    """프로듀서를 마감하고 판정한다. **두 겹을 한 번에 본다.**

        remaining = flush(timeout)   ← 아직 큐에 남은 것
        failed    = 콜백 누적         ← 만료로 영구 실패한 것 (flush 로는 0 으로 보인다)

    ⚠️ `flush()` 가 delivery report 를 마저 처리하므로, 이 순서(flush → 스냅샷)여야 한다.
    """
    t = trk or tracker()
    remaining = producer.flush(FLUSH_TIMEOUT if timeout is None else timeout) or 0
    delivered, failed, errors = t.snapshot()
    return DeliveryReport(delivered=delivered, failed=failed, remaining=remaining,
                          produced=produced, errors=errors)


def failures_since(baseline: int, trk: DeliveryTracker | None = None) -> int:
    """`baseline` 이후 늘어난 전달 실패 건수. 프로듀서를 계속 쓰는 경로(컨슈머 DLQ)용."""
    t = trk or tracker()
    _, failed, _ = t.snapshot()
    return max(0, failed - baseline)


__all__ = ["DELIVERY_TIMEOUT_MS", "FLUSH_TIMEOUT", "LOG_SAMPLE", "DeliveryFailed",
           "DeliveryReport", "DeliveryTracker", "failures_since", "finalize",
           "reset_tracker", "tracker"]
