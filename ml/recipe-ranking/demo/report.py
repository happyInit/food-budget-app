"""results.json → 발표용 HTML 리포트. 외부 의존 0(인라인 CSS), 라이트/다크 대응."""
from __future__ import annotations

import html


def _metric_card(title: str, ml: float, base: float, unit: str = "") -> str:
    lift = (ml - base) / base * 100 if base else 0.0
    cls = "up" if ml >= base else "down"
    return f"""<div class="card">
      <div class="ct">{html.escape(title)}</div>
      <div class="cv">{ml:.3f}{unit}</div>
      <div class="cb">규칙 {base:.3f} · <span class="{cls}">{lift:+.1f}%</span></div>
    </div>"""


def _rank_list(items: list[dict]) -> str:
    lis = []
    for i, it in enumerate(items, 1):
        badge = '<span class="match">취향</span>' if it["match"] else ""
        lis.append(f'<li><span class="rk">{i}</span><span class="nm">{html.escape(it["name"])}'
                   f'{badge}</span><span class="tg">{html.escape(it["tags"])}</span></li>')
    return "<ol class='ranks'>" + "".join(lis) + "</ol>"


def _persona_block(d: dict) -> str:
    return f"""<section class="persona">
      <h3>{html.escape(d['persona'])}</h3>
      <p class="desc">{html.escape(d['desc'])}</p>
      <div class="ba">
        <div class="col"><div class="colh rule">규칙 순위 (개인화 전)</div>{_rank_list(d['rule_top'])}</div>
        <div class="arrow">→</div>
        <div class="col"><div class="colh ml">ML 재랭킹 (개인화 후)</div>{_rank_list(d['ml_top'])}</div>
      </div>
    </section>"""


def render_html(results: dict) -> str:
    q = results["layer1"]
    ml, base = q["model"], q["baseline"]
    k = q["k"]
    cards = (_metric_card(f"NDCG@{k}", ml["ndcg@k"], base["ndcg@k"])
             + _metric_card(f"MAP@{k}", ml["map@k"], base["map@k"])
             + _metric_card("MRR", ml["mrr"], base["mrr"]))
    personas = "".join(_persona_block(d) for d in results["layer2"])
    lift = q["ndcg_lift"] * 100
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>개인화 랭킹 — 검증 리포트</title>
<style>
:root {{ --bg:#fff; --fg:#17264A; --mut:#6B7280; --line:#E6E6E6; --card:#FAFAFA; --acc:#F26419; --up:#1B9E5A; --dn:#C0392B; --rule:#8A94A6; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0F1522; --fg:#E8ECF3; --mut:#9AA4B5; --line:#26314A; --card:#151D2E; --acc:#FF7A3C; --up:#37D67A; --dn:#F06A5A; --rule:#6B7688; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font-family:-apple-system,'Segoe UI',Roboto,'Malgun Gothic',sans-serif; line-height:1.55; }}
.wrap {{ max-width:920px; margin:0 auto; padding:36px 22px 64px; }}
h1 {{ font-size:26px; letter-spacing:-.5px; margin:0 0 6px; }}
.sub {{ color:var(--mut); font-size:13.5px; margin:0 0 4px; }}
.note {{ display:inline-block; margin-top:12px; padding:6px 11px; background:var(--card); border:1px solid var(--line); border-radius:8px; font-size:12px; color:var(--mut); }}
h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:.6px; color:var(--mut); margin:38px 0 14px; }}
.hero {{ margin-top:20px; padding:20px 22px; border:1px solid var(--line); border-radius:14px; background:var(--card); }}
.hero .big {{ font-size:40px; font-weight:800; color:var(--acc); letter-spacing:-1px; }}
.hero .big span {{ font-size:16px; color:var(--mut); font-weight:600; }}
.cards {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
.card {{ border:1px solid var(--line); border-radius:12px; padding:15px 16px; background:var(--card); }}
.ct {{ font-size:12px; color:var(--mut); }}
.cv {{ font-size:28px; font-weight:800; letter-spacing:-.5px; margin:2px 0; font-variant-numeric:tabular-nums; }}
.cb {{ font-size:12px; color:var(--mut); }}
.up {{ color:var(--up); font-weight:700; }} .down {{ color:var(--dn); font-weight:700; }}
.persona {{ border:1px solid var(--line); border-radius:14px; padding:18px 20px; margin-bottom:16px; }}
.persona h3 {{ margin:0 0 2px; font-size:17px; }}
.desc {{ color:var(--mut); font-size:13px; margin:0 0 14px; }}
.ba {{ display:grid; grid-template-columns:1fr auto 1fr; align-items:start; gap:12px; }}
.colh {{ font-size:11.5px; font-weight:700; text-transform:uppercase; letter-spacing:.4px; padding:5px 9px; border-radius:6px; margin-bottom:9px; display:inline-block; }}
.colh.rule {{ color:var(--rule); border:1px solid var(--line); }}
.colh.ml {{ color:#fff; background:var(--acc); }}
.arrow {{ align-self:center; color:var(--acc); font-size:22px; font-weight:800; }}
ol.ranks {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:5px; }}
ol.ranks li {{ display:grid; grid-template-columns:auto 1fr auto; align-items:center; gap:8px; padding:7px 9px; border:1px solid var(--line); border-radius:8px; font-size:13px; }}
.rk {{ width:18px; height:18px; border-radius:50%; background:var(--line); color:var(--fg); font-size:11px; font-weight:700; display:flex; align-items:center; justify-content:center; }}
.nm {{ min-width:0; font-weight:600; }}
.match {{ margin-left:6px; font-size:10px; font-weight:700; color:var(--acc); border:1px solid var(--acc); border-radius:4px; padding:1px 4px; }}
.tg {{ font-size:11px; color:var(--mut); white-space:nowrap; }}
@media (max-width:640px) {{ .cards {{ grid-template-columns:1fr; }} .ba {{ grid-template-columns:1fr; }} .arrow {{ transform:rotate(90deg); }} }}
</style></head><body><div class="wrap">
<h1>개인화 레시피 랭킹 — 검증 리포트</h1>
<p class="sub">규칙 기반 랭킹(P0) 위에 LightGBM 재랭킹(P1)을 얹었을 때의 개선. 합성 페르소나 클릭스트림 기반.</p>
<div class="note">⚠️ 실사용자 데이터가 아닌 <b>mock 기반 오프라인 검증</b>입니다. 실운영 A/B(담기율)는 데이터 축적 후 측정.</div>

<div class="hero"><div class="big">{lift:+.1f}%<span> NDCG@{k} 개선 (규칙 대비)</span></div>
<div class="sub" style="margin-top:6px">검증 {q['n_val_groups']}개 노출요청 · 학습 {q['n_train_groups']}개 · 레시피 {results['n_recipes']}종 · 페르소나 {len(results['personas'])}종</div></div>

<h2>Layer 1 · 정량 평가 (ML vs 규칙 baseline)</h2>
<div class="cards">{cards}</div>

<h2>Layer 2 · 취향 반영 시연 (규칙 순위 → ML 재랭킹)</h2>
{personas}

<p class="sub" style="margin-top:26px">규칙 순위는 재고·임박·저비용만 보므로 취향과 무관하게 평평합니다. ML은 유저 행동(재료 선호·과거 참여)을 학습해
<b>'취향' 표시 레시피를 상위로</b> 끌어올립니다 — 이것이 개인화의 가치입니다.</p>
</div></body></html>"""
