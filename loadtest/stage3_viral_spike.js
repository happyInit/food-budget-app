// Stage3-B — "핫한" 유저의 레시피 등록 → 바이럴 트래픽 스파이크
//
// 🔴 전제(코드로 확인함, 추측 아님): 이 서비스에는 팔로우/구독이 없다.
//    notify 는 `GET /api/notifications` + `PATCH /{id}/read` 뿐이고 푸시 fan-out 경로가 없다.
//    그래서 "핫함"은 팔로워 푸시가 아니라 아래 둘로만 모델링한다:
//      ① 공유 링크(share_token) 단일 핫키에 read 폭증  ← 외부 채널(카톡·커뮤니티) 확산
//      ② publish 후 공개 목록 검색 노출로 유입
//
// 🔴 그리고 유저 등록 레시피는 ES 검색에 절대 안 나온다(설계상). 근거:
//    · POST /api/recipes/mine  → `insert into recipebook.user_recipe` (services/recipebook/app/queries.py:158)
//    · PGSync 는 `public.recipe` + `public.recipe_ingredient` 만 동기화 (deploy/pgsync/schema.json)
//    · services/recipe/ 에 recipebook 참조 0건 → `GET /api/recipes?q=` 는 절대 히트 안 함
//    · 실제 노출 경로 = 프론트가 `/api/recipes/shared?q=`(PG ILIKE)를 별도로 불러 클라이언트에서 합침
//    → 그래서 "신선도(H4)"는 CDC lag 측정이 아니라 **PG 즉시일관성 확인 + ES 음성 대조**로 재정의한다.
//
// B-3 순차 3단계 (startTime 으로 직렬화):
//    P1 등록(진짜 write) → P2 노출 신선도 → P3 단일 share_token 핫키 read 폭증
//
// 실행:
//   cp loadtest/stage3_viral_spike.js /mnt/c/temp/ &&
//   /mnt/c/temp/k6.exe run -e NUSERS=200 -e HOT_PEAK=200 'C:\temp\stage3_viral_spike.js'
//
// 선행: seed_users.js 로 NUSERS 만큼 유저 풀 시드.
// 🔴 write 는 전부 `TEST-` 접두. 런 종료 후 반드시 cleanup_test_recipes.js 실행.
//    (setup 이 만든 핫 레시피는 teardown 이 지우지만, P1/P2 가 만든 것은 cleanup 스크립트 담당)
// 🔴 LLM 경로 미포함 — /api/recipes/extract(video·Gemini)는 건드리지 않는다.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import exec from 'k6/execution';

// ── 파라미터 ────────────────────────────────────────────────────────────────
const IP        = __ENV.IP        || '192.168.0.14';
const HOST      = __ENV.HOST      || 'app.mealbong.cloud';
const PW        = __ENV.PW        || 'LoadTest2026!';
const NUSERS    = Number(__ENV.NUSERS    || 200);   // 시드된 유저 풀 크기
const TOKENS    = Number(__ENV.TOKENS    || 30);    // setup 에서 확보할 토큰 수
const PREFIX    = __ENV.PREFIX    || 'TEST-';       // 🔴 write 접두 — cleanup 셀렉터와 동일해야 함
const RUN_ID    = __ENV.RUN_ID    || String(Date.now()).slice(-8);

const WRITE_PEAK = Number(__ENV.WRITE_PEAK || 10);  // P1 등록 피크(레시피/s)
const WRITE_DUR  = __ENV.WRITE_DUR  || '90s';
const FRESH_RATE = Number(__ENV.FRESH_RATE || 1);   // P2 신선도 프로브(회/s)
const FRESH_DUR  = __ENV.FRESH_DUR  || '60s';
const HOT_START  = Number(__ENV.HOT_START || 5);    // P3 핫키 시작 rps
const HOT_PEAK   = Number(__ENV.HOT_PEAK  || 200);  // P3 핫키 피크 rps ← knee 탐색 손잡이
const DISC_RATE  = Number(__ENV.DISC_RATE || 10);   // P3 공개목록 검색(ILIKE) rps

// 타임라인 오프셋 — 겹치지 않게 여유를 둔다(B-3 "순차").
const T_P1 = 0;
const T_P2 = Number(__ENV.T_P2 || 100);   // P1(90s) 종료 후 10s
const T_P3 = Number(__ENV.T_P3 || 175);   // P2(60s) 종료 후 15s
const P3_DUR_S = Number(__ENV.P3_DUR_S || 195);

const HOT_VUS_MAX = Number(__ENV.HOT_VUS_MAX || Math.max(60, Math.ceil(HOT_PEAK * 1.5)));

// 🔴 k6 의 arrival-rate `rate`/`startRate`/`target` 은 **정수만** 받는다 → 램프 계산은 전부 반올림.
const stepW = (f) => Math.max(1, Math.round(WRITE_PEAK * f));
const stepH = (f) => Math.max(HOT_START, Math.round(HOT_PEAK * f));

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  scenarios: {
    // ── P1. 등록 버스트 (진짜 write) ──────────────────────────────────────
    // 바이럴이 터지면 "나도 올려볼까" 로 등록 자체가 늘어난다. recipebook write 경로 실측.
    p1_register: {
      executor: 'ramping-arrival-rate',
      startRate: 1, timeUnit: '1s',
      preAllocatedVUs: 20, maxVUs: Math.max(60, Math.ceil(WRITE_PEAK * 6)),
      stages: [
        { target: stepW(0.3), duration: '30s' },
        { target: stepW(1.0), duration: '30s' },
        { target: stepW(1.0), duration: '30s' },
      ],
      exec: 'registerRecipe', startTime: `${T_P1}s`,
    },

    // ── P2. 노출 신선도 (등록 → publish → 공개목록에 보이기까지) ──────────
    // 같은 트랜잭션이라 이론상 0초여야 한다. 그 "이론상"을 실측으로 확인하고,
    // 동시에 ES 카탈로그(`/api/recipes?q=`)에는 영원히 안 나온다는 음성 대조를 남긴다.
    p2_freshness: {
      executor: 'constant-arrival-rate',
      rate: Math.max(1, Math.round(FRESH_RATE)), timeUnit: '1s', duration: FRESH_DUR,
      preAllocatedVUs: 10, maxVUs: 40,
      exec: 'freshnessProbe', startTime: `${T_P2}s`,
    },

    // ── P3-a. 🔴 단일 share_token 핫키 read 폭증 (바이럴 본체) ────────────
    // 비인증. 캐시 없음. 한 행에 read 가 집중된다 = 핫키.
    p3_hotkey: {
      executor: 'ramping-arrival-rate',
      startRate: HOT_START, timeUnit: '1s',
      preAllocatedVUs: Math.min(60, HOT_VUS_MAX), maxVUs: HOT_VUS_MAX,
      stages: [
        { target: stepH(0.15), duration: '30s' },
        { target: stepH(0.35), duration: '30s' },
        { target: stepH(0.60), duration: '30s' },
        { target: stepH(1.00), duration: '45s' },
        { target: stepH(1.00), duration: '60s' },   // 고원 ★ 측정 구간
      ],
      exec: 'hotKeyRead', startTime: `${T_P3}s`,
    },

    // ── P3-b. 공개 목록 검색 (publish 후 검색 유입) ────────────────────────
    // 🔴 `where s.title ilike '%q%' or s.ingredients::text ilike '%q%'` = 인덱스 못 타는 seq scan
    //    (shared_recipe 의 유일한 인덱스는 published_at DESC). 여기가 먼저 무너질 후보다.
    p3_discovery: {
      executor: 'constant-arrival-rate',
      rate: Math.max(1, Math.round(DISC_RATE)), timeUnit: '1s', duration: `${P3_DUR_S}s`,
      preAllocatedVUs: 20, maxVUs: Math.max(60, Math.ceil(DISC_RATE * 8)),
      exec: 'discoverySearch', startTime: `${T_P3}s`,
    },
  },
  thresholds: {
    // ── SLO 판정(비중단) ──
    'http_req_duration{name:recipe_create}':  ['p(95)<1000'],   // write
    'http_req_duration{name:recipe_publish}': ['p(95)<1000'],   // write
    'http_req_duration{name:shared_hotkey}':  ['p(95)<500'],    // 단순조회 — 바이럴 핵심 SLO
    'http_req_duration{name:shared_search}':  ['p(95)<1000'],   // 검색/집계
    'http_req_duration{name:catalog_search}': ['p(95)<1000'],   // ES 대조군
    // ── 오류율 SLO(<1%) + 🔴 안전 킬스위치(>10% 면 중단) ──
    http_req_failed:   [
      'rate<0.01',
      { threshold: 'rate<0.10',  abortOnFail: true, delayAbortEval: '15s' },
    ],
    http_req_duration: [{ threshold: 'p(95)<3000', abortOnFail: true, delayAbortEval: '15s' }],
  },
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };

// 커스텀 지표
const freshnessMs   = new Trend('freshness_shared_ms');   // publish → 공개목록 노출까지(ms)
const freshnessPoll = new Trend('freshness_polls');       // 몇 번 폴링해서 보였나
const catalogLeak   = new Counter('catalog_es_hits');     // 🔴 ES 카탈로그에 새 레시피가 나온 횟수(기대 0)
const createdOk     = new Counter('recipes_created');
const publishedOk   = new Counter('recipes_published');

function poolEmail(i) { return `loadtest-pool-${String(i).padStart(4, '0')}@mealbong.cloud`; }

// 🔴 모든 write 제목은 이 함수로만 만든다 — cleanup 셀렉터(PREFIX)와 단일 규약.
function testTitle(kind, uniq) { return `${PREFIX}${RUN_ID}-${kind}-${uniq}`; }

function recipeBody(title) {
  return {
    title,
    ingredients: [
      { name: '김치', quantity: '1/2포기' },
      { name: '돼지고기', quantity: '200g' },
      { name: '두부', quantity: '1모' },
      { name: '대파', quantity: '1대' },
      { name: '고춧가루', quantity: '1큰술' },
    ],
    steps: ['김치를 볶는다', '고기를 넣고 볶는다', '물을 붓고 끓인다', '두부와 대파를 넣는다'],
    cooking_time: '30분 이내',
    serving: '1인분',
    level_nm: '초급',
  };
}

// ── setup: 토큰 확보 + "핫한" 레시피 1건 등록·발행 → share_token ────────────
export function setup() {
  const n = Math.min(TOKENS, NUSERS);
  const tokens = [];
  for (let i = 1; i <= n; i++) {
    const r = http.post(`https://${HOST}/api/auth/login`,
      JSON.stringify({ email: poolEmail(i), password: PW }), JSON_H);
    if (r.status === 200) tokens.push(r.json('access_token'));
  }
  if (tokens.length === 0) {
    throw new Error('setup: 토큰 0개 — seed_users.js 로 유저 풀을 먼저 시드했는지 확인');
  }

  const hotAuth = { 'Content-Type': 'application/json', Authorization: `Bearer ${tokens[0]}` };
  const hotTitle = testTitle('VIRAL', 'hot');
  const cr = http.post(`https://${HOST}/api/recipes/mine`,
    JSON.stringify(recipeBody(hotTitle)), { headers: hotAuth });
  if (cr.status !== 201) throw new Error(`setup: 핫 레시피 등록 실패 status=${cr.status} body=${cr.body}`);
  const hotId = cr.json('id');

  const pb = http.post(`https://${HOST}/api/recipes/mine/${hotId}/publish`, null, { headers: hotAuth });
  if (pb.status !== 200) throw new Error(`setup: publish 실패 status=${pb.status} body=${pb.body}`);
  const hotToken = pb.json('share_token');

  console.log(`setup: tokens=${tokens.length} · hotId=${hotId} · hotToken=${hotToken} · RUN_ID=${RUN_ID}`);
  console.log(`setup: 🔴 정리 대상 접두 = "${PREFIX}${RUN_ID}" — 런 후 cleanup_test_recipes.js -e PREFIX=${PREFIX}`);
  return { tokens, hotId, hotToken, hotTitle };
}

// ── P1. 등록(진짜 write) ────────────────────────────────────────────────────
export function registerRecipe(data) {
  const tk = data.tokens[Math.floor(Math.random() * data.tokens.length)];
  const title = testTitle('REG', `${exec.scenario.iterationInTest}`);
  const r = http.post(`https://${HOST}/api/recipes/mine`,
    JSON.stringify(recipeBody(title)),
    { headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tk}` },
      tags: { name: 'recipe_create' } });
  if (check(r, { 'create 201': (res) => res.status === 201 })) createdOk.add(1);
}

// ── P2. 노출 신선도 + ES 음성 대조 ──────────────────────────────────────────
// 등록 → publish → `/api/recipes/shared?q=<고유제목>` 이 보일 때까지 폴링(최대 30회 · 1s 간격).
// 같은 트랜잭션이라 1회차에 보이는 게 정상. 안 보이면 그 자체가 발견이다.
export function freshnessProbe(data) {
  const tk = data.tokens[Math.floor(Math.random() * data.tokens.length)];
  const auth = { 'Content-Type': 'application/json', Authorization: `Bearer ${tk}` };
  const uniq = `${exec.scenario.iterationInTest}`;
  const title = testTitle('FRESH', uniq);

  const cr = http.post(`https://${HOST}/api/recipes/mine`,
    JSON.stringify(recipeBody(title)), { headers: auth, tags: { name: 'recipe_create' } });
  if (cr.status !== 201) return;
  createdOk.add(1);
  const rid = cr.json('id');

  const t0 = Date.now();
  const pb = http.post(`https://${HOST}/api/recipes/mine/${rid}/publish`, null,
    { headers: auth, tags: { name: 'recipe_publish' } });
  if (!check(pb, { 'publish 200': (r) => r.status === 200 })) return;
  publishedOk.add(1);

  // ① PG 경로(실제 노출 경로) — 보일 때까지 폴링
  let seen = false, polls = 0;
  for (let i = 0; i < 30; i++) {
    polls++;
    const ls = http.get(`https://${HOST}/api/recipes/shared?q=${encodeURIComponent(title)}&limit=5`,
      { tags: { name: 'shared_search' } });
    if (ls.status === 200) {
      const rows = ls.json('recipes') || [];
      if (rows.some((x) => x.title === title)) { seen = true; break; }
    }
    sleep(1);
  }
  if (seen) { freshnessMs.add(Date.now() - t0); freshnessPoll.add(polls); }
  check(seen, { '공개목록 30s 내 노출': (v) => v === true });

  // ② 🔴 ES 카탈로그 음성 대조 — 설계상 절대 0이어야 한다(catalog_es_hits == 0 이 정상).
  const cs = http.get(`https://${HOST}/api/recipes?q=${encodeURIComponent(title)}`,
    { headers: auth, tags: { name: 'catalog_search' } });
  if (cs.status === 200 && (cs.json('total') || 0) > 0) catalogLeak.add(1);
}

// ── P3-a. 단일 share_token 핫키 read (비인증) ───────────────────────────────
// 🔴 싸 보이지만 안 싸다: 핸들러가 enrich_ingredients 로 PG 왕복 4회를 추가로 친다
//    (services/recipebook/app/queries.py:24-75 — unnest 이름매칭 + item_master + 가격 + 영양).
export function hotKeyRead(data) {
  const r = http.get(`https://${HOST}/api/recipes/shared/${encodeURIComponent(data.hotToken)}`,
    { tags: { name: 'shared_hotkey' } });
  check(r, { 'hotkey 200': (res) => res.status === 200 });
}

// ── P3-b. 공개 목록 검색(ILIKE seq scan) ────────────────────────────────────
export function discoverySearch() {
  const r = http.get(`https://${HOST}/api/recipes/shared?q=${encodeURIComponent(PREFIX)}&limit=30`,
    { tags: { name: 'shared_search' } });
  check(r, { 'shared_search 200': (res) => res.status === 200 });
}

// ── teardown: setup 이 만든 핫 레시피 제거(멱등) ─────────────────────────────
// user_recipe 삭제 시 shared_recipe 는 FK ON DELETE CASCADE 로 함께 사라진다.
// P1/P2 가 만든 레시피는 cleanup_test_recipes.js 가 담당(여기서 다 못 지운다).
export function teardown(data) {
  const auth = { Authorization: `Bearer ${data.tokens[0]}` };
  const d = http.del(`https://${HOST}/api/recipes/mine/${data.hotId}`, null, { headers: auth });
  console.log(`teardown: hot 레시피 삭제 status=${d.status} (204/404 정상)`);
  console.log(`teardown: 🔴 남은 ${PREFIX} 레시피 정리 = k6 run -e NUSERS=${NUSERS} -e PREFIX=${PREFIX} cleanup_test_recipes.js`);
}
