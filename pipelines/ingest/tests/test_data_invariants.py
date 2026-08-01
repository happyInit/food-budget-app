"""불변식 점검기 — **하드/소프트 분리가 무너지지 않게** 고정한다.

로직 대부분이 SQL 이라 값 검증은 운영 PG 대조로 했다(하드 6개 전부 0 · 소프트 11/149/360/16).
여기서는 **이 장치를 쓸모없게 만드는 변경**을 막는다.
"""
import re
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "data_invariants.py").read_text()


def _consts():
    ns = {}
    exec(compile(re.search(r"HARD = \[.*?\n\]", _SRC, re.S).group(0), "<h>", "exec"), ns)
    exec(compile(re.search(r"SOFT = \[.*?\n\]", _SRC, re.S).group(0), "<s>", "exec"), ns)
    return ns["HARD"], ns["SOFT"]


def test_every_check_explains_what_violation_means():
    """위반이 **무엇을 뜻하는지** 없으면 경보를 받은 사람이 판단할 수 없다."""
    hard, soft = _consts()
    for name, sql, meaning in hard + soft:
        assert name and sql.strip() and meaning.strip(), name
        assert len(meaning) >= 15, f"의미 설명이 너무 짧다: {name}"


def test_all_checks_are_read_only():
    """🔴 점검기가 데이터를 바꾸면 안 된다 — 진단이 원인이 되어선 안 된다."""
    hard, soft = _consts()
    # 🔴 **단어 경계로 본다.** 단순 부분일치로 두면 `created_at` 이 CREATE 로 잡힌다
    #    (이 테스트를 처음 쓸 때 실제로 걸렸다 — "조건이 너무 넓다"의 교과서 사례).
    banned = re.compile(
        r"\b(INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM|DROP\s+|ALTER\s+|TRUNCATE\s+|CREATE\s+(TABLE|INDEX|VIEW))",
        re.I)
    for name, sql, _ in hard + soft:
        m = banned.search(sql)
        assert m is None, f"{name} 에 쓰기 구문: {m.group(0) if m else ''}"


def test_soft_signals_are_not_hard_invariants():
    """소프트로 분류한 것이 하드로 올라오면 **매주 헛경보**가 울린다.

    운영 데이터로 재보니 두 후보는 불변식이 아니었다:
      · `expire_at < created_at` — 유저가 직접 수정 가능(_PATCH_COLS 에 expire_at)
      · `(item,storage)` 중복 source — 전부 item_id NULL 이라 lookup 에 영향 없음
    가짜 실패가 섞이면 사람은 경보를 무시하기 시작하고 **진짜가 가려진다.**
    """
    hard, soft = _consts()
    hard_names = " ".join(n for n, _, _ in hard)
    assert "만료일" not in hard_names, "유저 수정 가능한 값을 하드로 두면 헛경보"
    soft_names = " ".join(n for n, _, _ in soft)
    assert "만료일" in soft_names


def test_shelf_life_duplicate_check_is_scoped_to_matched_items():
    """중복 source 점검은 `item_id IS NOT NULL` 로 좁혀야 한다.

    `lookup_shelf_life` 가 `item_id` 로 조인하므로 NULL 행은 조회에 영향이 없다.
    좁히지 않으면 현재 3건이 잡혀 **첫 실행부터 실패**한다(실측).
    """
    hard, _ = _consts()
    sql = next(s for n, s, _ in hard if "중복" in n)
    assert "item_id IS NOT NULL" in sql


def test_exit_codes_distinguish_violation_from_connection_failure():
    """0=통과 · 1=하드 위반 · 2=접속 실패. 2 를 1 과 섞으면 **환경 문제를 결함으로 오인**한다."""
    assert "return 2" in _SRC and "return 1" in _SRC and "return 0" in _SRC
    assert "0=통과" in _SRC and "1=하드 불변식 위반" in _SRC and "2=DB 접속 실패" in _SRC
