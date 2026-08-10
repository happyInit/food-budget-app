"""price 는 `app/config.py` 에 **모듈 전역 `settings = Settings()`** 가 있다(옛 패턴).

🔴 그래서 JWT_SECRET 은 fixture 가 아니라 **conftest 로드 시점**에 넣어야 한다(0-12).
   jwt_secret 의 placeholder 폴백을 없앴으므로, env 없이 `app.config` 를 import 하면
   그 자리에서 ConfigError 로 죽는다 — 테스트 모듈보다 먼저 로드되는 conftest 가 유일한 자리다.
   os.environ 을 **덮어쓴다**(setdefault 아님) — 셸에 실 비밀이 export 돼 있어도 테스트는 격리된다.
"""
from __future__ import annotations

import os

TEST_JWT_SECRET = "test-secret-0123456789abcdef0123456789"  # ≥32자 (JWT_SECRET_MIN_LEN)
os.environ["JWT_SECRET"] = TEST_JWT_SECRET
