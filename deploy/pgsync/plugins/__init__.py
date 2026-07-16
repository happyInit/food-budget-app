"""PGSync 플러그인 패키지.

PGSync 는 이 `plugins` 패키지를 walk 해서 `pgsync.plugin.Plugin` 서브클래스를
찾고, schema.json 의 `plugins: [...]` 에 나열된 이름(`klass.name`)과 매칭되는
것만 인스턴스화한다(별도 PLUGINS env 없음 — 패키지 탐색 방식).

배포: 공식 이미지 `toluaina1/pgsync`(WORKDIR=/app)의 `/app/plugins/` 로 이 디렉터리를
마운트해야 로드됨. `__init__.py` 가 있어야 import 가능한 패키지가 된다.
"""
