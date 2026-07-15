"""Recipe Service — 레시피 탐색·상세 (데이터 티어 읽기).
docs/design/api-spec.md #18 GET /api/recipes · #19 GET /api/recipes/{id}.
JWT 미검증(Gateway/Auth 서비스 나오면 추가) — chat 서비스와 동일 방침.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from app.config import settings
from app.db import make_pg_pool
from app.models import RecipeDetail, RecipeListResponse
from app.queries import get_detail, search_pg

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    state["pg_pool"] = make_pg_pool()
    await state["pg_pool"].open()
    try:
        yield
    finally:
        await state["pg_pool"].close()


app = FastAPI(title="Recipe Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "recipe"}


@app.get("/api/recipes", response_model=RecipeListResponse)
async def list_recipes(
    q: str | None = Query(None, description="레시피명·재료 검색어"),
    tag: str | None = Query(None, description="카테고리(요리종류) 필터"),
    cooking_time: str | None = Query(None, description="조리시간 태그 (예: '15분 이내')"),
    level: str | None = Query(None, description="난이도 태그 (예: '아무나')"),
    page: int = Query(1, ge=1),
    size: int = Query(settings.page_size, ge=1, le=100),
):
    # ES 인덱스(recipes) 적재 후 search_backend="es" 로 전환. 현재는 PG.
    cards, total = await search_pg(state["pg_pool"], q, tag, page, size, cooking_time, level)
    return RecipeListResponse(recipes=cards, page=page, size=size, total=total)


@app.get("/api/recipes/{recipe_id}", response_model=RecipeDetail)
async def recipe_detail(recipe_id: int):
    detail = await get_detail(state["pg_pool"], recipe_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="recipe not found")
    return detail
