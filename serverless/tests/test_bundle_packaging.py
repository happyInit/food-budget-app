"""번들 포장 규약 — **배포 후 첫 호출에서야 드러나는** 실수를 빌드 전에 잡는다.

여기 있는 것은 전부 실제로 한 번씩 밟은 지뢰다. 공통점은 셋이다:
  · 빌드가 **성공**한다
  · 번들 크기가 **정상**으로 보인다
  · 그런데 Lambda 첫 호출에서 `ModuleNotFoundError` / 핸들러 못 찾음으로 죽는다
로컬 import 로는 확인이 안 된다(번들은 py3.12·aarch64 라 이 기계에서 안 뜬다).
그래서 **정적 규약**으로 못 박는다.
"""
import re
from pathlib import Path

import pytest

SERVERLESS = Path(__file__).resolve().parents[1]
ROOT = SERVERLESS.parent
BUILD = ROOT / ".build"


def _functions():
    return sorted(p for p in SERVERLESS.iterdir()
                  if p.is_dir() and (p / "modules.txt").exists())


def _module_entries(fn: Path):
    return [ln.strip() for ln in (fn / "modules.txt").read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


# ── ① 진입점 이름이 담는 패키지와 부딪히지 않는가 ────────────────────────────
def test_app_패키지를_담는_함수는_진입점이_app_py_가_아니다():
    """🔴 `import app` 은 **패키지가 모듈을 이긴다**(실측). 번들 루트에 `app/` 이 서는데
    진입점도 `app.py` 면, Lambda 핸들러 문자열 `app.handler` 가 패키지 쪽을 집어
    «handler 가 없다» 로 죽는다. chat·ocr 처럼 앱이 패키지 구조인 함수가 여기 해당한다."""
    for fn in _functions():
        담는_패키지 = {Path(m).name for m in _module_entries(fn) if (ROOT / m).is_dir()}
        if "app" not in 담는_패키지:
            continue
        assert not (fn / "app.py").exists(), (
            f"{fn.name}: `app/` 패키지를 담으면서 진입점도 app.py 다 — 이름이 부딪힌다. "
            f"handler.py 로 두고 Lambda 핸들러를 `handler.handler` 로 지정할 것")
        assert (fn / "handler.py").exists(), f"{fn.name}: 진입점 handler.py 가 없다"


def test_모든_함수에_진입점과_requirements_가_있다():
    for fn in _functions():
        진입점 = [p.name for p in fn.glob("*.py") if p.name in ("app.py", "handler.py")]
        assert 진입점, f"{fn.name}: app.py 도 handler.py 도 없다"
        src = (fn / 진입점[0]).read_text(encoding="utf-8")
        assert re.search(r"^def handler\(", src, re.M), f"{fn.name}: `def handler(` 가 없다"


# ── ② 심볼릭 링크가 번들에 들어가지 않는가 ───────────────────────────────────
def test_레포에_vendor_심볼릭_링크가_실재한다():
    """이 사실이 아래 `-L` 규약의 **근거**다. 링크가 사라지면 이 테스트가 먼저 깨지고,
    그때는 규약이 아니라 이 테스트를 지우는 게 맞다."""
    links = sorted(p.relative_to(ROOT) for p in (ROOT / "services").rglob("*.py")
                   if p.is_symlink() and ".venv" not in p.parts)
    assert links, "services/ 아래 심볼릭 링크가 하나도 없다 — 규약의 전제가 바뀌었다"
    assert any("chat" in str(p) for p in links), f"chat 의 vendor 링크가 없다: {links}"


def test_build_sh_가_링크를_실체로_푼다():
    """🔴 `cp -R` 은 링크를 **링크째** 복사한다. `services/chat/app/vendor/quantity.py` 는
    `../../../../pipelines/ingest/quantity.py` 를 가리키는데 번들에는 그 경로가 없다
    → 첫 호출에서 `No module named 'app.vendor.quantity'`. 실제로 밟았다(2026-08-17)."""
    src = (SERVERLESS / "build.sh").read_text(encoding="utf-8")
    assert "cp -RL" in src, "build.sh 가 디렉터리를 `cp -RL` 로 복사하지 않는다"
    assert re.search(r"find .*-type l", src), "build.sh 에 심볼릭 링크 잔존 가드가 없다"


@pytest.mark.parametrize("fn", [p.name for p in _functions()])
def test_빌드된_번들에_심볼릭_링크가_없다(fn):
    """`.build/` 가 있을 때만 본다 — CI 에서는 스킵되고, 로컬에서 빌드한 뒤에는 실제 검사가 된다."""
    out = BUILD / fn
    if not out.exists():
        pytest.skip(f"{fn}: 빌드 산출물 없음")
    남은 = [str(p.relative_to(out)) for p in out.rglob("*") if p.is_symlink()]
    assert not 남은, f"{fn}: 번들에 심볼릭 링크가 남았다 — {남은}"


# ── ③ manifest 가 가리키는 것이 실재하는가 ───────────────────────────────────
@pytest.mark.parametrize("fn", [p.name for p in _functions()])
def test_manifest_항목이_전부_실재한다(fn):
    """빌드가 «manifest 항목 없음» 으로 죽기 전에 여기서 먼저 알려준다."""
    없음 = [m for m in _module_entries(SERVERLESS / fn) if not (ROOT / m).exists()]
    assert not 없음, f"{fn}: modules.txt 가 없는 경로를 가리킨다 — {없음}"
