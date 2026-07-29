"""video 서비스 라우트 — Gemini·Redis 없이 계약 검증.

`ml/video-recipe` 라이브러리 재사용(하이픈 디렉터리 import)이 실제로 되는지도 함께 확인한다.
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("VIDEO_GEMINI_API_KEY", "test-key")

from app import main as m  # noqa: E402
from app.models import VideoStatusResponse  # noqa: E402


class _FakeStore:
    """Redis 대체 — 잡·캐시·락을 메모리에서."""

    def __init__(self):
        self.jobs, self.cache, self.locks = {}, {}, set()

    async def put_job(self, jid, payload): self.jobs[jid] = payload
    async def get_job(self, jid): return self.jobs.get(jid)
    async def get_cached(self, url): return self.cache.get(url)
    async def set_cached(self, url, r): self.cache[url] = r
    async def acquire(self, url):
        if url in self.locks:
            return False
        self.locks.add(url); return True
    async def release(self, url): self.locks.discard(url)
    async def ping(self): return True


@pytest.fixture
def client():
    store = _FakeStore()
    m.state["store"] = store
    with TestClient(m.app) as c:      # lifespan이 store를 덮어쓰므로 진입 후 재주입
        m.state["store"] = store
        yield c, store


def test_library_import_works():
    """하이픈 디렉터리(`ml/video-recipe`) 재사용이 실제로 되는지 — 서비스의 전제."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ml" / "video-recipe"))
    from pipeline import normalize_url

    assert normalize_url("https://www.youtube.com/watch?v=abc12345678")
    assert normalize_url("https://example.com/notyoutube") is None


def test_health_reports_dependencies(client):
    c, _ = client
    body = c.get("/health").json()
    assert body["status"] == "ok"
    assert body["redis"] is True
    assert body["gemini_key"] is True          # 키 '값'이 아니라 존재 여부만


def test_rejects_non_youtube_url(client):
    c, _ = client
    r = c.post("/api/recipes/extract", json={"url": "https://example.com/video"})
    assert r.status_code == 400


def test_accepts_and_returns_job_id(client):
    c, store = client
    r = c.post("/api/recipes/extract", json={"url": "https://www.youtube.com/watch?v=abc12345678"})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    assert store.jobs[jid]["status"] in ("PENDING", "DONE", "FAILED")


def test_cache_hit_skips_analysis(client):
    """다른 유저가 이미 분석한 영상 → Gemini 호출 없이 즉시 DONE(비용 0)."""
    c, store = client
    url = "https://www.youtube.com/watch?v=cached123456"
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ml" / "video-recipe"))
    from pipeline import normalize_url

    store.cache[normalize_url(url)] = {
        "title": "김치찌개", "is_recipe": True, "ingredients": [], "steps": [],
    }
    r = c.post("/api/recipes/extract", json={"url": url})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "DONE" and body["from_cache"] is True


def test_single_flight_rejects_duplicate(client):
    """같은 영상이 분석 중이면 409 — 중복 Gemini 호출 방지."""
    c, store = client
    url = "https://www.youtube.com/watch?v=dup123456789"
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ml" / "video-recipe"))
    from pipeline import normalize_url

    store.locks.add(normalize_url(url))
    assert c.post("/api/recipes/extract", json={"url": url}).status_code == 409


def test_unknown_job_is_404(client):
    c, _ = client
    assert c.get("/api/recipes/extract/nonexistent").status_code == 404


def test_status_schema_roundtrip():
    """저장 payload가 응답 스키마로 그대로 복원되는지(잡 저장 형식 계약)."""
    payload = {"status": "DONE", "stage": "extracted", "title": "된장찌개",
               "ingredients": [{"name": "두부", "quantity": "1모"}],
               "steps": [{"order": 1, "text": "끓인다", "timestamp_sec": 30}]}
    out = VideoStatusResponse(**payload)
    assert out.title == "된장찌개"
    assert out.ingredients[0].name == "두부"
    assert out.steps[0].timestamp_sec == 30


def test_servings_unknown_is_flagged_not_invented():
    """인분 미상은 추정하지 않고 플래그로 드러낸다 — 틀린 인분은 재료비를 왜곡한다."""
    known = VideoStatusResponse(status="DONE", servings="2인분", servings_known=True)
    assert known.servings == "2인분" and known.servings_known is True

    unknown = VideoStatusResponse(status="DONE", servings=None, servings_known=False)
    assert unknown.servings is None and unknown.servings_known is False
