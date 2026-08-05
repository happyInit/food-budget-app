"""GET /api/recipes/shared — ES(nori) 발행 목록/검색. get_es 만 fake 로 실 ES 없이 검증."""
from __future__ import annotations

import pytest

import app.main as main_mod
from app.context import get_es
from tests.fakes import FakeEs

OV = main_mod.app.dependency_overrides


def test_shared_list_no_q_sends_match_all(client):
    # q 미지정이면 DSL 은 match_all + 최신 발행순 정렬(ILIKE 동작 보존).
    es = FakeEs()
    OV[get_es] = lambda: es
    r = client.get("/api/recipes/shared")
    assert r.status_code == 200
    assert es.last_kwargs["query"] == {"match_all": {}}
    assert es.last_kwargs["sort"] == [{"published_at": "desc"}]


def test_shared_list_q_sends_multi_match(client):
    # q 는 multi_match '값' 으로만 전달 — query_string(ES 문법 해석) 금지 → 검색 문법 주입 불가(A05).
    es = FakeEs()
    OV[get_es] = lambda: es
    r = client.get("/api/recipes/shared?q=김치")
    assert r.status_code == 200
    mm = es.last_kwargs["query"]["multi_match"]
    assert mm["query"] == "김치"
    assert mm["fields"] == ["title", "ingredient_names"]
    assert mm["type"] == "cross_fields"
    assert mm["operator"] == "and"
    assert "query_string" not in es.last_kwargs["query"]


def test_shared_list_maps_source_to_card(client):
    # _source → 카드 1:1, published_at 은 ISO 문자열로 datetime 파싱 경로 태움, image_url None 도 섞음.
    hits = [
        {"id": 1, "title": "우리집 김치찌개", "image_url": "http://img/1.jpg",
         "origin": "MANUAL", "share_token": "tok_a", "published_at": "2026-07-16T10:00:00+00:00"},
        {"id": 2, "title": "된장국", "image_url": None, "origin": "MANUAL",
         "share_token": "tok_b", "published_at": "2026-07-16T11:00:00+00:00"},
    ]
    OV[get_es] = lambda: FakeEs(hits=hits)
    r = client.get("/api/recipes/shared")
    assert r.status_code == 200
    cards = r.json()["recipes"]
    assert len(cards) == 2
    assert cards[0] == {"id": 1, "title": "우리집 김치찌개", "image_url": "http://img/1.jpg",
                        "origin": "MANUAL", "share_token": "tok_a",
                        "published_at": "2026-07-16T10:00:00Z"}
    assert cards[1]["image_url"] is None
    assert "user_id" not in cards[0]            # 작성자 식별정보 미노출


def test_shared_list_empty_hits_ok(client):
    # hits 비면 빈 목록 200 — 빈결과는 오류가 아니라 정상 응답.
    OV[get_es] = lambda: FakeEs(hits=[])
    r = client.get("/api/recipes/shared")
    assert r.status_code == 200
    assert r.json() == {"recipes": []}


def test_shared_list_limits_clamped(client):
    # 핸들러 min(max(limit,1),60) — 0은 1로 오르고, 999는 60으로 잘린다(미지정은 기본 30).
    for qs, expect in [("?limit=0", 1), ("?limit=999", 60), ("", 30)]:
        es = FakeEs()
        OV[get_es] = lambda: es
        assert client.get(f"/api/recipes/shared{qs}").status_code == 200
        assert es.last_kwargs["size"] == expect


def test_shared_list_es_failure_raises(client):
    # ES 장애는 PG 폴백 없음(설계) — TestClient(raise_server_exceptions=True)는 500 대신 예외를 올린다.
    OV[get_es] = lambda: FakeEs(raise_exc=RuntimeError("es down"))
    with pytest.raises(RuntimeError):
        client.get("/api/recipes/shared")
