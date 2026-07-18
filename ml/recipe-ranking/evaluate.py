"""랭킹 평가 하네스 — NDCG@k·MAP·MRR, 그룹(노출요청)별 산출 후 평균.

규칙 baseline(rule_score) 대비 ML이 얼마나 나은지 비교하는 게 핵심 — P1의 가치 증명.
numpy만 사용.
"""
from __future__ import annotations

import numpy as np


def _dcg(rels: np.ndarray, k: int) -> float:
    rels = np.asarray(rels, dtype=float)[:k]
    if rels.size == 0:
        return 0.0
    gains = (2.0**rels - 1.0) / np.log2(np.arange(2, rels.size + 2))
    return float(gains.sum())


def ndcg_at_k(y_true: np.ndarray, y_score: np.ndarray, groups: np.ndarray, k: int = 10) -> float:
    """그룹별 NDCG@k 평균. y_score 내림차순으로 정렬한 관련도의 DCG ÷ 이상 DCG."""
    out = []
    for g in np.unique(groups):
        m = groups == g
        yt, ys = y_true[m], y_score[m]
        ranked = yt[np.argsort(-ys, kind="stable")]
        ideal = np.sort(yt)[::-1]
        idcg = _dcg(ideal, k)
        out.append(_dcg(ranked, k) / idcg if idcg > 0 else 0.0)
    return float(np.mean(out)) if out else 0.0


def map_at_k(y_true: np.ndarray, y_score: np.ndarray, groups: np.ndarray, k: int = 10) -> float:
    """그룹별 Average Precision@k 평균(관련=relevance≥1의 이진 판정)."""
    out = []
    for g in np.unique(groups):
        m = groups == g
        rel = (y_true[m] >= 1).astype(int)
        ranked = rel[np.argsort(-y_score[m], kind="stable")][:k]
        if ranked.sum() == 0:
            out.append(0.0); continue
        hits = np.cumsum(ranked)
        prec = hits / (np.arange(ranked.size) + 1)
        out.append(float((prec * ranked).sum() / ranked.sum()))
    return float(np.mean(out)) if out else 0.0


def mrr(y_true: np.ndarray, y_score: np.ndarray, groups: np.ndarray) -> float:
    """그룹별 Mean Reciprocal Rank(첫 관련 항목의 역순위) 평균."""
    out = []
    for g in np.unique(groups):
        m = groups == g
        rel = (y_true[m] >= 1).astype(int)[np.argsort(-y_score[m], kind="stable")]
        pos = np.flatnonzero(rel)
        out.append(1.0 / (pos[0] + 1) if pos.size else 0.0)
    return float(np.mean(out)) if out else 0.0


def evaluate(y_true: np.ndarray, y_score: np.ndarray, groups: np.ndarray, k: int = 10) -> dict:
    return {
        "ndcg@k": ndcg_at_k(y_true, y_score, groups, k),
        "map@k": map_at_k(y_true, y_score, groups, k),
        "mrr": mrr(y_true, y_score, groups),
    }


def compare(y_true, model_score, baseline_score, groups, k: int = 10) -> dict:
    """ML vs 규칙 baseline. 'lift'=NDCG 상대 개선율(양수면 ML이 나음)."""
    m = evaluate(y_true, model_score, groups, k)
    b = evaluate(y_true, baseline_score, groups, k)
    lift = (m["ndcg@k"] - b["ndcg@k"]) / b["ndcg@k"] if b["ndcg@k"] > 0 else 0.0
    return {"model": m, "baseline": b, "ndcg_lift": lift}
