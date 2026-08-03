"""백그라운드 OCR 잡 태스크가 GC 로 증발하지 않는지 — 회귀 방지.

이벤트 루프는 Task 를 **약참조로만** 들고 있다. `asyncio.create_task()` 의 반환값을 아무도
붙잡지 않으면 실행 도중 GC 가 회수할 수 있고, 그러면 영수증 잡이 예외도 로그도 없이 사라진
채 상태만 PENDING 으로 남는다(asyncio 공식 문서 경고 · SonarQube S7502).

`_run_job` 은 Gemini 호출로 수 초간 await 하므로 회수 창이 넓다 — 실서비스에서 물릴 수 있는
조건이라 계약으로 못박는다: (1) 실행 중엔 강한 참조가 살아 있고 (2) 끝나면 스스로 빠진다.
"""
import asyncio
import io

import pytest
from fastapi import UploadFile

from app import main
from app.models import OcrStatusResponse


class _FakeStore:
    """put/get 만 쓰는 최소 저장소 — Redis 없이 _accept 를 돌리기 위한 것."""

    backing = "memory"

    def __init__(self):
        self.jobs: dict[str, OcrStatusResponse] = {}

    async def put(self, job_id, status):
        self.jobs[job_id] = status

    async def get(self, job_id):
        return self.jobs.get(job_id)


def _upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="receipt.jpg")


@pytest.mark.asyncio
async def test_running_job_is_strongly_referenced(monkeypatch):
    """실행 중인 잡 태스크는 모듈이 강한 참조를 들고 있어야 한다 — 없으면 GC 로 증발."""
    started, release = asyncio.Event(), asyncio.Event()

    async def _fake_run_job(job_id, image):
        started.set()
        await release.wait()          # Gemini 호출로 오래 await 하는 구간을 흉내

    monkeypatch.setattr(main, "_run_job", _fake_run_job)
    monkeypatch.setitem(main.state, "store", _FakeStore())
    main._jobs.clear()

    resp = await main._accept(_upload(b"fake-image-bytes"))
    assert resp.status == "PENDING"

    await asyncio.wait_for(started.wait(), timeout=1)
    assert main._jobs, "실행 중 태스크에 강한 참조가 없다 — GC 가 잡을 회수할 수 있다"

    tasks = list(main._jobs)          # done 콜백이 집합을 바꾸므로 스냅샷을 뜬다
    release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_finished_job_is_released(monkeypatch):
    """끝난 태스크는 집합에서 빠져야 한다 — 안 그러면 참조가 무한히 쌓여 누수가 된다."""

    async def _fake_run_job(job_id, image):
        return None

    monkeypatch.setattr(main, "_run_job", _fake_run_job)
    monkeypatch.setitem(main.state, "store", _FakeStore())
    main._jobs.clear()

    await main._accept(_upload(b"fake-image-bytes"))
    tasks = list(main._jobs)
    await asyncio.gather(*tasks)
    await asyncio.sleep(0)            # done 콜백은 call_soon 이라 한 턴 더 돌려준다

    assert not main._jobs, "완료된 태스크가 해제되지 않았다 — 참조 누수"
