"""테스트 공통 준비 — **import 순서에 기대지 않기 위해** 여기서 한다.

🔴 종전엔 `test_routes.py` 가 모듈 최상단에서 `os.environ.setdefault(...)` 로 키를 심고
   그 **다음 줄에서** `app.main` 을 import 했다. `Settings` 는 import 시점에 만들어지는
   싱글턴이라, 다른 테스트 파일이 먼저 `app.config` 를 건드리면 키 없는 설정이 굳는다
   → 라우트가 503("아직 준비되지 않았어요")을 돌려주고 **엉뚱한 테스트가 깨진다.**
   실제로 파일 하나(`test_budget_cap.py`)가 알파벳순으로 앞서면서 그 일이 났다(2026-09-02).

   pytest 는 테스트 모듈보다 conftest 를 먼저 읽으므로, 여기 두면 **수집 순서와 무관하게**
   환경이 준비된다. 새 테스트 파일을 추가할 때 이 함정을 다시 밟지 않는다.
"""
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()

# `app` 패키지 import 경로 (services/video)
sys.path.insert(0, str(_HERE.parents[1]))

# 🔵 `setdefault` 라 실제 환경에 값이 있으면 존중한다 — CI 가 진짜 키를 줄 수도 있다.
os.environ.setdefault("VIDEO_GEMINI_API_KEY", "test-key")
