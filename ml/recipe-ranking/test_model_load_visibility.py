"""모델 적재 실패가 드러나는가 — 체크리스트 `1-21` 〔이슈 #561〕.

`1-21` 이 지적한 결함:
  serve.py 가 파일 부재·pickle 실패를 **로그 없이** 삼키고 model=None 으로 기동한다.
  /health 는 status: ok 를 반환해 readiness·liveness 를 둘 다 통과한다.
  ⇒ "규칙순 폴백 중"인지 "ML 이 도는 중"인지 **밖에서 구분할 방법이 없다**.

🔴 이 테스트가 지키는 선:
  ① /health 의 status 는 **계속 ok** 여야 한다 — 여기서 실패하면 readiness 가 떨어져
     규칙순 폴백조차 못 한다(모델 없이도 서빙하는 것이 의도된 설계다).
  ② 대신 **왜 없는지가 실려야** 한다 — 세 원인(env 미설정 / 파일 부재 / 로드 실패)이 구분돼야 한다.
  ③ 각 경우에 **로그가 남아야** 한다 (이게 1-21 의 핵심 — 종전엔 완전 침묵)

C-20(모델을 이미지에 굽기)으로 가면 *"이미지 배선이 틀려도 드러나지 않는"* 경로가 되므로
이 가시성이 특히 중요하다.
"""
from __future__ import annotations

import logging
import pickle
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


class FakeModel:
    """pickle 가능한 더미 랭커. 🔴 모듈 레벨이어야 한다 — 중첩 클래스는 pickle 이 경로를 못 찾는다
    (`train.py:8` 이 `_LgbRanker` 를 모듈 레벨에 둔 것과 같은 이유)."""

    def predict(self, X):   # 모델 인터페이스(대문자 X = ML 관례)
        return [0.0] * len(X)


@pytest.fixture()
def serve(monkeypatch):
    """env 를 바꾼 뒤 `_init_from_env()` 를 다시 돌려 기동 상태를 재현한다.

    🔴 `sys.modules.pop("serve")` + 재import 를 쓰지 않는다 — `serve` 는 모듈 레벨 전역
       (`_ranker`·`_model_status`)을 들고 있어서, 그렇게 하면 **이 파일이 다른 테스트 파일의
       serve 상태를 오염시킨다**(실측: 단독 14건 통과 → 합치면 2건 실패).
       teardown 에서 env 를 되돌리고 한 번 더 초기화해 **모듈을 원래대로** 남긴다.
    """
    import serve as m

    def _load():
        m._init_from_env()
        return m

    yield _load
    monkeypatch.undo()      # env 원복이 먼저 — 그 다음 초기화해야 원상태가 된다
    m._init_from_env()


def _health(m):
    from fastapi.testclient import TestClient
    return TestClient(m.app).get("/health").json()


# ── ① status 는 항상 ok (readiness 를 떨어뜨리면 폴백조차 못 한다) ──────────
@pytest.mark.parametrize("case", ["env_unset", "file_missing", "load_failed"])
def test_health_status_stays_ok_in_every_failure(serve, monkeypatch, tmp_path, case):
    if case == "env_unset":
        monkeypatch.delenv("RANKING_MODEL_PATH", raising=False)
    elif case == "file_missing":
        monkeypatch.setenv("RANKING_MODEL_PATH", str(tmp_path / "없는파일.pkl"))
    else:
        bad = tmp_path / "broken.pkl"
        bad.write_bytes(b"not a pickle")
        monkeypatch.setenv("RANKING_MODEL_PATH", str(bad))

    body = _health(serve())
    assert body["status"] == "ok", "readiness 가 떨어지면 규칙순 폴백조차 못 한다"
    assert body["model_loaded"] is False
    assert body["model_source"] == case, "왜 없는지가 구분돼야 한다"


# ── ② 정상 적재는 출처·크기까지 드러낸다 ────────────────────────────────
def test_health_exposes_provenance_when_loaded(serve, monkeypatch, tmp_path):
    p = tmp_path / "ranker.pkl"
    p.write_bytes(pickle.dumps(FakeModel()))
    monkeypatch.setenv("RANKING_MODEL_PATH", str(p))

    body = _health(serve())
    assert body["model_loaded"] is True
    assert body["model_source"] == "file"
    assert body["model_bytes"] == p.stat().st_size
    assert body["model_class"] == "FakeModel"


# ── ③ 세 실패 모두 로그를 남긴다 — 1-21 의 핵심 ─────────────────────────
@pytest.mark.parametrize(
    ("case", "needle"),
    [("env_unset", "RANKING_MODEL_PATH 미설정"),
     ("file_missing", "모델 파일이 없다"),
     ("load_failed", "모델 로드 실패")],
)
def test_every_failure_is_logged(serve, monkeypatch, tmp_path, caplog, case, needle):
    if case == "env_unset":
        monkeypatch.delenv("RANKING_MODEL_PATH", raising=False)
    elif case == "file_missing":
        monkeypatch.setenv("RANKING_MODEL_PATH", str(tmp_path / "없는파일.pkl"))
    else:
        bad = tmp_path / "broken.pkl"
        bad.write_bytes(b"not a pickle")
        monkeypatch.setenv("RANKING_MODEL_PATH", str(bad))

    with caplog.at_level(logging.WARNING, logger="ranking-serving"):
        serve()
    assert any(needle in r.message for r in caplog.records), (
        f"{case} 가 조용히 지나갔다 — 이게 1-21 이 지적한 결함이다")


# ── ④ /reload 실패도 로그를 남긴다 (재학습이 깨진 모델을 저장한 순간) ─────
def test_reload_failure_is_logged_and_keeps_old_model(serve, monkeypatch, tmp_path, caplog):
    p = tmp_path / "ranker.pkl"
    p.write_bytes(pickle.dumps(FakeModel()))
    monkeypatch.setenv("RANKING_MODEL_PATH", str(p))
    m = serve()
    assert _health(m)["model_loaded"] is True

    p.write_bytes(b"corrupted by retrain")   # 재학습이 깨진 모델을 저장한 상황
    with caplog.at_level(logging.ERROR, logger="ranking-serving"):
        from fastapi.testclient import TestClient
        body = TestClient(m.app).post("/reload").json()

    assert body["reloaded"] is False
    assert any("모델 재적재 실패" in r.message for r in caplog.records)
    assert _health(m)["model_loaded"] is True, "실패 시 기존 모델을 유지해야 한다(다운그레이드 금지)"
