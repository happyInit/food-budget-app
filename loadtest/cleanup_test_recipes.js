// Stage3 정리 — `TEST-` 접두 유저 레시피 멱등 삭제
//
// 실행:
//   cp loadtest/cleanup_test_recipes.js /mnt/c/temp/ &&
//   /mnt/c/temp/k6.exe run -e NUSERS=200 'C:\temp\cleanup_test_recipes.js'
//   특정 런만:  -e PREFIX=TEST-12345678      (stage3_viral_spike 의 RUN_ID 까지 포함)
//   드라이런:   -e DRYRUN=1                  (세지만 지우지 않음)
//
// 🔴 셀렉터는 **이중 잠금**이라 실제 유저 데이터에 닿을 수 없다:
//   ① 계정 스코프 — `loadtest-pool-NNNN@mealbong.cloud` 로만 로그인한다. `/api/recipes/mine` 은
//      JWT 의 user_id 로 `where user_id = %s` 스코프가 걸려 있어(services/recipebook/app/queries.py),
//      이 스크립트는 **테스트 계정이 소유한 행 외에는 애초에 볼 수도 없다.**
//   ② 제목 접두 — 그 안에서 다시 `title.startsWith(PREFIX)` 인 것만 지운다.
//   두 조건을 모두 통과해야 DELETE 가 나간다. PREFIX 가 4자 미만이면 시작을 거부한다.
//
// 멱등: 두 번 돌리면 두 번째는 삭제 0건(이미 없음). 실패해도 재실행 안전.
// 부수효과: user_recipe 삭제 시 recipebook.shared_recipe 는 FK ON DELETE CASCADE 로 함께 사라진다
//          (docs/prd/schema-production.sql) → 별도 unpublish 불필요.

import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import exec from 'k6/execution';

const IP     = __ENV.IP     || '192.168.0.14';
const HOST   = __ENV.HOST   || 'app.mealbong.cloud';
const PW     = __ENV.PW     || 'LoadTest2026!';
const NUSERS = Number(__ENV.NUSERS || 200);      // 훑을 유저 풀 크기(시드한 만큼)
const PREFIX = __ENV.PREFIX || 'TEST-';          // 🔴 삭제 셀렉터 — write 스크립트와 동일해야 함
const DRYRUN = __ENV.DRYRUN === '1';

if (PREFIX.length < 4) {
  throw new Error(`PREFIX 가 너무 짧다("${PREFIX}") — 오삭제 방지를 위해 4자 이상만 허용한다`);
}

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  scenarios: {
    cleanup: {
      executor: 'shared-iterations',
      vus: Number(__ENV.VUS || 5),
      iterations: NUSERS,           // 유저 1명당 1 이터레이션
      maxDuration: __ENV.MAXDUR || '30m',
    },
  },
  // 정리 스크립트는 abortOnFail 을 걸지 않는다 — 중간에 끊기면 쓰레기가 남는다.
  thresholds: {},
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };

const scanned = new Counter('recipes_scanned');
const matched = new Counter('recipes_matched');
const deleted = new Counter('recipes_deleted');
const skipped = new Counter('users_skipped');   // 로그인 실패(계정 없음) = 정상

export function setup() {
  console.log(`cleanup: PREFIX="${PREFIX}" · NUSERS=${NUSERS} · DRYRUN=${DRYRUN}`);
  return {};
}

export default function () {
  const i = exec.scenario.iterationInTest + 1;
  const email = `loadtest-pool-${String(i).padStart(4, '0')}@mealbong.cloud`;

  // ① 계정 스코프 — 테스트 계정으로만 로그인. 실패 = 그 계정 없음(정상, 넘어감).
  const lo = http.post(`https://${HOST}/api/auth/login`,
    JSON.stringify({ email, password: PW }), JSON_H);
  if (lo.status !== 200) { skipped.add(1); return; }
  const auth = { Authorization: `Bearer ${lo.json('access_token')}` };

  // ② 내 레시피 목록 — JWT user_id 스코프라 남의 행은 응답에 들어올 수 없다.
  const ls = http.get(`https://${HOST}/api/recipes/mine`, { headers: auth, tags: { name: 'mine_list' } });
  if (!check(ls, { 'mine_list 200': (r) => r.status === 200 })) return;
  const rows = ls.json('recipes') || [];
  scanned.add(rows.length);

  // ③ 제목 접두 필터 — 여기를 통과한 것만 지운다.
  for (const r of rows) {
    const title = String(r.title || '');
    if (!title.startsWith(PREFIX)) continue;      // 🔴 유일한 삭제 조건
    matched.add(1);
    if (DRYRUN) { console.log(`[dryrun] would delete id=${r.id} title=${title}`); continue; }
    const d = http.del(`https://${HOST}/api/recipes/mine/${r.id}`, null,
      { headers: auth, tags: { name: 'recipe_delete' } });
    if (check(d, { 'delete 204/404': (x) => x.status === 204 || x.status === 404 })) {
      if (d.status === 204) deleted.add(1);
    }
  }
}

export function teardown() {
  console.log('cleanup: 완료 — recipes_scanned / recipes_matched / recipes_deleted 카운터를 요약에서 확인.');
  console.log('cleanup: 두 번째 실행에서 recipes_matched=0 이면 정리 완결(멱등 확인).');
}
