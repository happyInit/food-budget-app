"""분류 캐스케이드 (§7.2) — OCR 다운스트림. 라이브 호출 없이 룩업·규칙으로 대부분 처리.

품목 하나가 아래 계단을 내려가다 맞으면 멈춘다(싼 것부터):
  0. 경계정책표(생수·얼음·홍삼정 등 정책 확정어)         [파일]
  1. is_food=false → 비식품                              [OCR 출력]
  2/6. gazetteer 매칭(exact→suffix→token→prefix) → 식재료 [dict_item_master]
  3/4. food_nutrition·oasis 파생 → 가공식품               [TODO: DB 필요, 현재 skip]
  5. shelf_life 시드 / 규칙셋 → 보관법                    [파일/코드]
  7. 미해결 → LLM(실시간)                                [훅만, 아직 미배선]

새 대용량 데이터 저술 0 — 전부 레포 기존 자산 재사용. 파일 없으면 해당 단계만 skip.
설계 근거: docs/ocr-nonfood-handling-proposal.md §7.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

# 레포 실행 시 = …/food-budget-app(parents[4]). 컨테이너(…/app 로만 COPY)는 깊이가 얕아
# parents[4]가 없으므로 안전하게 폴백 — 파일 부재 → 각 _load_*가 skip(도크스트링대로 DB gazetteer 사용).
_parents = Path(__file__).resolve().parents
_REPO = _parents[4] if len(_parents) > 4 else _parents[-1]
_DEF_DICT = _REPO / "ml/ingredient-ner/data/dict_item_master.txt"
_DEF_SHELF = _REPO / "pipelines/ingest/data/kr_shelf_life_seed.csv"   # DB 폴백용 로컬 시드(정본은 shelf_life_ref)

INGREDIENT = "식재료"
PROCESSED = "가공식품"
NONFOOD = "비식품"         # 비식품 '상품'(세제·봉투·화장지) — 식비=total에서 **차감**
ADJUSTMENT = "조정"        # 할인·쿠폰·포인트·음수라인 — total에 이미 반영 → **차감 안 함**(§7.3.5)

# 경계정책(§7.7) — 데이터가 아니라 **분류 정책(결정)** 이므로 코드에 둔다(PR리뷰·테스트·git이력 대상).
#   키=공백제거 term → (category, in_expense=식비포함). 정본 문서: pipelines/ingest/data/edge_case_food_policy.csv
#   (사람이 읽는 시드/근거. 이 상수와 동일 내용을 유지).
_EDGE_POLICY: dict[str, tuple[str, bool]] = {
    "생수": (PROCESSED, True),    # 식품(음용수) — 식비 포함
    "얼음": (PROCESSED, True),    # 식품 — 식비 포함
    "홍삼정": (NONFOOD, False),   # 건강기능식품 — 식비 제외
}

# 조정(할인/쿠폰/포인트) 이름 규칙 — 비식품 '상품'과 구분(차감 대상 아님).
_ADJUST_KW = ("할인", "쿠폰", "포인트", "적립", "에누리", "세일", "멤버십", "임직원", "제휴")

# 보관법 규칙(§7.4) — shelf_life 시드가 못 채운 잔여분. 데이터 아니라 코드 몇 줄.
_FREEZER_KW = ("냉동", "아이스", "빙수")
_FRIDGE_KW = ("우유", "두부", "계란", "달걀", "생선", "고기", "육", "김치", "요구르트", "요거트",
              "치즈", "햄", "어묵", "두유", "나물", "젓갈", "회", "초밥", "샐러드", "버섯")
_ROOM_KW = ("라면", "통조림", "식용유", "설탕", "소금", "밀가루", "부침가루", "튀김가루", "과자",
            "즉석밥", "시리얼", "커피", "차", "음료", "견과", "김", "미역", "당면", "국수", "파스타")

# 명백한 비식품 규칙셋(코드) — is_food로 안 걸리는 마트 공산품(세제·화장지·담배 등). §7.3.3.
#   식비에서 제외되어야 하는데 gazetteer(식재료 사전)엔 없어 미해결로 새는 것 방지.
_NONFOOD_KW = ("세제", "세정", "섬유유연", "유연제", "표백", "화장지", "휴지", "물티슈", "티슈",
               "기저귀", "건전지", "배터리", "봉투", "담배", "라이터", "종이컵", "호일", "위생장갑",
               "수세미", "비누", "샴푸", "린스", "바디워시", "치약", "칫솔", "면도", "생리대", "사료")

# 용량·단위 접미 제거(§7.5 ①) — "돈생삼겹살500g" → "돈생삼겹살" 후 접미매칭 성립.
_MEASURE_RE = re.compile(
    r"\d+(\.\d+)?(kg|g|ml|l|ℓ|리터|매|장|개입|개|입|팩|봉지|봉|병|캔|미|송이|단|포|구|근|줄|모|쪽|인분|호|px?)?$",
    re.IGNORECASE,
)


def _strip_measure(nc: str) -> str:
    stripped = _MEASURE_RE.sub("", nc).strip()
    return stripped or nc


@dataclass
class Classification:
    category: str | None          # 식재료/가공식품/비식품, None=미해결(§7.3.4)
    storage: str | None           # FRIDGE/FREEZER/ROOM, None=비-pantry
    in_expense: bool              # 식비 포함 여부(§7.3.5: 식비=식품 금액합)
    needs_review: bool            # HITL 하이라이트(§7.6): 저신뢰·미해결
    tier: str                     # 어느 단계에서 결정됐나(진단·로그)
    item_id: int | None = None    # item_master 표준품목코드(DB 연결 시만; 파일 폴백=None)


def _nospace(s: str | None) -> str:
    return (s or "").replace(" ", "")


def _load_dict(path: Path) -> dict[str, tuple[int | None, str]]:
    """dict_item_master(한 줄=식재료명) → gazetteer 사전. item_id는 백엔드가 실DB로 채움(여기선 None)."""
    if not path.exists():
        return {}
    gaz: dict[str, tuple[int | None, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.strip()
        if name:
            gaz.setdefault(_nospace(name), (None, name))
    return gaz


def _load_shelf(path: Path) -> dict[str, str]:
    """item_name→storage. 여러 행이면 첫 행 우선(시드 저자 순서 존중)."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = _nospace(row.get("item_name"))
            st = (row.get("storage") or "").strip().upper()
            if key and st and key not in out:
                out[key] = st
    return out


# (경계정책표는 DB/파일이 아니라 _EDGE_POLICY 코드 상수로 이동 — §7.7 정책=로직)


# 종세분화 가드(정책2 동물) — pipelines/ingest/gazetteer.py와 동일 로직 복제(ocr standalone 유지).
_SPECIES_QUALIFIERS = [
    ("돼지고기", "돼지"), ("소고기", "소"), ("닭고기", "닭"), ("오리고기", "오리"), ("양고기", "양"),
    ("엘에이", "소"), ("한우", "소"),
    ("돼지", "돼지"), ("오리", "오리"), ("소", "소"), ("닭", "닭"), ("LA", "소"), ("la", "소"),
]
_CANON_SPECIES = {"소고기": "소", "돼지고기": "돼지", "닭고기": "닭", "오리고기": "오리", "양고기": "양"}
_SPECIES_EXCLUDE = ("양념", "양파", "양배추", "양상추", "소금", "소스", "소면")


def _leading_species(prefix: str):
    for ex in _SPECIES_EXCLUDE:
        if ex in prefix:
            return None
    for q, sp in _SPECIES_QUALIFIERS:
        if prefix.startswith(q):
            return sp
    return None


def _make_matcher(gaz: dict[str, tuple[int | None, str]], meat_canons: frozenset = frozenset()):
    """공백제거 exact → 최장 접미 → 최장 토큰 → 최장 prefix. services/chat gazetteer 로직 재사용.
    반환 (item_id, canonical, method) — item_id는 DB 연결 시만 채워짐(파일 폴백=None).
    meat_canons 주어지면 종세분화 가드(정책2): 육류 head + 종 수식어 충돌/generic → 종 remap."""
    aliases = sorted(gaz.keys(), key=len, reverse=True)
    species_item = {sp: gaz[c] for c, sp in _CANON_SPECIES.items() if c in gaz}

    def match(name: str | None) -> tuple[int | None, str | None, str]:
        nc = _strip_measure(_nospace(name))
        if not nc:
            return (None, None, "")
        if nc in gaz:
            return gaz[nc] + ("exact",)
        for a in aliases:
            if len(a) >= 2 and nc.endswith(a):
                canon_a = gaz[a][1]
                if meat_canons and canon_a in meat_canons:
                    qsp = _leading_species(nc[: -len(a)])
                    if qsp is not None:
                        csp = _CANON_SPECIES.get(canon_a)
                        if csp is None or csp != qsp:
                            if qsp in species_item:
                                return species_item[qsp] + ("guard-remap",)
                            return (None, None, "guard-block")
                return gaz[a] + ("suffix",)
        for tok in sorted((name or "").split(), key=len, reverse=True):
            if _nospace(tok) in gaz:
                return gaz[_nospace(tok)] + ("token",)
        for a in aliases:
            if len(a) >= 2 and nc.startswith(a):
                return gaz[a] + ("prefix",)
        return (None, None, "")

    return match


def _load_gazetteer_db() -> dict[str, tuple[int | None, str]]:
    """item_alias→(item_id, canonical)을 실 DB에서 1회 로드. **읽기 전용·단기 커넥션**.

    가드레일(docs/ocr-nonfood-handling-proposal.md §7, 위험분석): SELECT만, read_only 트랜잭션,
    기동 시 커넥션 1개 후 즉시 close(영속 풀 X), public 데이터 티어만. 실패 시 {} → 파일 폴백.
    쿼리는 services/chat gazetteer(load_gazetteer)와 동일.
    """
    if not settings.pgpassword:
        return {}, frozenset()
    try:
        import psycopg  # 지연 import — 미설치 시 파일 폴백
    except Exception:
        return {}, frozenset()
    try:
        with psycopg.connect(
            host=settings.pghost, port=settings.pgport, dbname=settings.pgdatabase,
            user=settings.pguser, password=settings.pgpassword,
            connect_timeout=5, autocommit=True,
        ) as conn:
            conn.read_only = True                       # 쓰기 원천 차단(fbapp 광역계정 대비)
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '5s'")
                cur.execute("""select a.alias, a.item_id, m.canonical_name
                               from item_alias a join item_master m on m.item_id = a.item_id""")
                gaz = {_nospace(al): (iid, canon) for al, iid, canon in cur.fetchall()}
                cur.execute("select canonical_name from item_master where category = '육류'")
                return gaz, frozenset(r[0] for r in cur.fetchall())   # 종세분화 가드용 육류 canonical
    except Exception:
        return {}, frozenset()                          # 어떤 실패든 파일 폴백(서비스는 계속)


def _load_shelf_db() -> dict[str, str]:
    """보관법 시드를 정본 `shelf_life_ref`(source='CURATED' 한글 큐레이션)에서 1회 DB 로드.

    gazetteer와 동일 가드: SELECT만·read_only·단기 커넥션. item_name→storage 매핑이며,
    한 품목에 다중 storage 행이 있으면 `order by id` **첫 행 우선**(kr_shelf_life_seed.csv 저자순 재현).
    실패/부재 → {} → 파일(_load_shelf) 폴백 → 그래도 없으면 _storage_for가 키워드/기본 FRIDGE.
    """
    if not settings.pgpassword:
        return {}
    try:
        import psycopg  # 지연 import — 미설치 시 파일 폴백
    except Exception:
        return {}
    try:
        with psycopg.connect(
            host=settings.pghost, port=settings.pgport, dbname=settings.pgdatabase,
            user=settings.pguser, password=settings.pgpassword,
            connect_timeout=5, autocommit=True,
        ) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '5s'")
                if cur.execute("select to_regclass('shelf_life_ref')").fetchone()[0] is None:
                    return {}
                cur.execute("""select item_name, storage from shelf_life_ref
                               where source = 'CURATED' and item_name is not null and storage is not null
                               order by id""")
                out: dict[str, str] = {}
                for name, st in cur.fetchall():
                    key, sv = _nospace(name), (st or "").strip().upper()
                    if key and sv and key not in out:   # 첫 행 우선(CSV 의미 재현)
                        out[key] = sv
                return out
    except Exception:
        return {}                                        # 어떤 실패든 파일/키워드 폴백


class Classifier:
    """참조 데이터를 1회 로드해 캐스케이드 분류를 제공(서비스 기동 시 생성)."""

    def __init__(self) -> None:
        dict_p = Path(settings.dict_item_master_path) if settings.dict_item_master_path else _DEF_DICT
        shelf_p = Path(settings.shelf_life_path) if settings.shelf_life_path else _DEF_SHELF
        # gazetteer: DB 우선(실 item_id·풍부한 alias) → 실패 시 파일
        db_gaz, meat_canons = _load_gazetteer_db()
        self._gaz = db_gaz or _load_dict(dict_p)
        self.gaz_source = "db" if db_gaz else "file"
        self._match = _make_matcher(self._gaz, meat_canons)   # 파일 폴백 시 ∅ → 가드 off
        # 보관법: DB 정본(shelf_life_ref) 우선 → 실패 시 파일 → (없으면 _storage_for 키워드/기본)
        db_shelf = _load_shelf_db()
        self._shelf = db_shelf or _load_shelf(shelf_p)
        self.shelf_source = "db" if db_shelf else "file"
        # 경계정책: 데이터 아님 → 코드 상수(§7.7). DB/파일 로드 없음.
        self._edge = _EDGE_POLICY

    def _storage_for(self, name: str | None) -> str:
        """보관법: shelf_life 시드 → 규칙셋 → 기본 냉장(§7.4). 원문 기준(냉동*·아이스 접두 보존)."""
        nc = _strip_measure(_nospace(name))
        if nc in self._shelf:
            return self._shelf[nc]
        for a in sorted(self._shelf, key=len, reverse=True):   # 접미(백다다기오이→오이 계열)
            if len(a) >= 2 and nc.endswith(a):
                return self._shelf[a]
        if any(k in (name or "") for k in _FREEZER_KW):
            return "FREEZER"
        if any(k in (name or "") for k in _ROOM_KW):
            return "ROOM"
        if any(k in (name or "") for k in _FRIDGE_KW):
            return "FRIDGE"
        return "FRIDGE"                                        # 기본 냉장(안전측)

    def classify(self, name: str | None, is_food: bool = True, price=None) -> Classification:
        nc = _nospace(name)
        neg = price is not None and price < 0
        adjust_name = any(k in (name or "") for k in _ADJUST_KW)

        # -1. 조정(할인·쿠폰·포인트·음수라인) → 품목 아님, pantry 제외, **식비 차감 대상 아님**(total에 이미 반영).
        #     부호-종류 불일치는 OCR 오정렬 의심 → HITL 플래그(§7.6):
        #       · 할인/쿠폰 이름인데 양수(쿠폰 +3,000=식품값 오배치) · 음수인데 할인/쿠폰 이름 아님(식품에 -1,200 오배치)
        if neg or adjust_name:
            suspicious = (adjust_name and price is not None and price > 0) or (neg and not adjust_name)
            return Classification(ADJUSTMENT, None, in_expense=False, needs_review=suspicious, tier="adjust")

        # 0. 경계정책표
        if nc in self._edge:
            cat, inexp = self._edge[nc]
            st = self._storage_for(name) if cat == INGREDIENT else None
            return Classification(cat, st, inexp, needs_review=False, tier="edge")

        # 1. is_food=false → 비식품
        if not is_food:
            return Classification(NONFOOD, None, in_expense=False, needs_review=False, tier="is_food")

        # 1.5. 비식품 규칙셋(세제·담배 등) → 비식품·식비 제외
        if any(k in (name or "") for k in _NONFOOD_KW):
            return Classification(NONFOOD, None, in_expense=False, needs_review=False, tier="nonfood_kw")

        # 2/6. gazetteer 매칭 → 식재료
        item_id, canon, method = self._match(name)
        if canon:
            exact = method == "exact"
            return Classification(INGREDIENT, self._storage_for(name), in_expense=True,
                                  needs_review=not exact, tier=f"gazetteer:{method}", item_id=item_id)

        # 3/4. food_nutrition·oasis 파생 → TODO(DB 필요). 현재 skip.

        # 7. 미해결 → 식비 포함 + 확인 플래그(§7.3.4). LLM 훅은 아래(아직 미배선).
        return Classification(None, "FRIDGE", in_expense=True, needs_review=True, tier="unresolved")


def _is_adjust_name(name: str | None) -> bool:
    return any(k in (name or "") for k in _ADJUST_KW)


def realign_prices(items) -> bool:
    """OCR 가격-품목 오정렬 보수적 교정 (§7.3.5 3층 · docs §7.6).

    Gemini가 가격을 인접 줄로 오배치하는 케이스(맥도날드: 쿠폰↔스낵랩) 복원.
    **불변 규칙**: 조정(할인·쿠폰)은 음수·품목은 양수여야 한다. 이를 어긴 쌍이
    **정확히 한 쌍**일 때만(조정-양수 1개 ∧ 비조정-음수 1개) 두 가격을 스왑(합계 보존).
    애매하면(0개·2개↑) **손대지 않음** → HITL ★플래그가 처리. 반환 = 스왑 수행 여부.
    """
    adj_pos = [it for it in items
               if it.price is not None and it.price > 0 and _is_adjust_name(it.name)]
    item_neg = [it for it in items
                if it.price is not None and it.price < 0 and not _is_adjust_name(it.name)]
    if len(adj_pos) == 1 and len(item_neg) == 1:
        adj_pos[0].price, item_neg[0].price = item_neg[0].price, adj_pos[0].price
        # 가격과 함께 is_food 도 되돌린다. 엔진이 이 줄에 is_food=false 를 붙인 근거는
        # **음수 가격 자체**("음수=할인")인데, 그 음수가 오배치였다고 방금 판정했으므로
        # 전제가 사라진다. 남겨두면 티어1(is_food=false)에서 needs_review 없이 조용히
        # 탈락해 **식비에서 품목이 통째로 증발한다** — 스왑 전에는 티어-1 이 의심 플래그를
        # 세워 HITL 이 잡던 건이라, 복구가 오히려 안전망을 지우는 역전이 생긴다.
        # 진짜 비식품(봉투·비닐 등)은 이름 기반 티어1.5 _NONFOOD_KW 가 그대로 걸러낸다 —
        # true 로 단정하는 게 아니라 **이름 캐스케이드에 판정을 되돌려주는 것**이다.
        if not item_neg[0].is_food:
            item_neg[0].is_food = True
        return True
    return False


# 서비스 전역 1회 로드(파이프라인에서 재사용)
_classifier: Classifier | None = None


def get_classifier() -> Classifier:
    global _classifier
    if _classifier is None:
        _classifier = Classifier()
    return _classifier
