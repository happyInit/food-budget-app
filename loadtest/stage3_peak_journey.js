// Stage3-A — 점심·저녁 피크 몰림 (20-30대 1인가구 페르소나 · open 모델)
//
// 왜 open 모델(ramping-arrival-rate)인가:
//   식사시간 몰림은 "서버가 느려져도 유입이 계속되는" 유입이다. closed-VU(ramping-vus)는
//   서버가 느려지면 VU가 대기에 묶여 도착률이 저절로 줄어 붕괴를 숨긴다(=coordinated omission).
//   Stage1 §3.3 은 closed 였으므로, 이번엔 open 으로 같은 축을 다시 본다.
//
// 두 축을 같은 시간축에 겹친다 (Stage1 §3.4 "천장은 유입 패턴의 함수"를 그대로 이어받음):
//   · peak_login  = 새 세션 로그인 도착(account bcrypt 축)
//   · peak_browse = 세션당 브라우징 버스트 10 req(recipe/price/recipebook/pantry/notify 축)
//   둘 다 같은 세션 도착률 λ 로 램프한다 → 총 요청 ≈ λ × 11 req/s.
//
// 규모: DAU 500 baseline = λ 0.4 세션/s (산출 근거 = docs/mp_k6_stage3_peak_viral.md §3).
//   -e MULT=<성장 배수> 로 그 위를 탐색한다. MULT=10 ≈ DAU 5,000 등가.
//
// 실행:
//   cp loadtest/stage3_peak_journey.js /mnt/c/temp/ &&
//   /mnt/c/temp/k6.exe run -e NUSERS=200 -e MULT=1 'C:\temp\stage3_peak_journey.js'
//   knee 탐색:  -e MODE=knee -e MULT=100   (계단 램프 · 각 단 45s 유지 = HPA 반응 시간 확보)
//
// 선행: seed_users.js 로 NUSERS 만큼 유저 풀 시드.
// 🔴 write 없음(로그인 제외). LLM 경로(OCR·chat·video) 미포함.
// 안전: 오류율>10% 또는 전체 p95>3s 면 abortOnFail 로 자동 중단.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

// ── 파라미터 (전부 -e 로 주입 가능) ──────────────────────────────────────────
const IP      = __ENV.IP      || '192.168.0.14';
const HOST    = __ENV.HOST    || 'app.mealbong.cloud';
const PW      = __ENV.PW      || 'LoadTest2026!';
const NUSERS  = Number(__ENV.NUSERS  || 200);   // 시드된 유저 풀 크기
const TOKENS  = Number(__ENV.TOKENS  || 30);    // setup 에서 미리 로그인해 둘 토큰 수(브라우징용)
const MULT    = Number(__ENV.MULT    || 1);     // 성장 배수 (1 = DAU 500 baseline)
const BASE    = Number(__ENV.BASE    || 0.4);   // baseline 피크 세션 도착률(세션/s) — §3 산출값
const MODE    = __ENV.MODE    || 'peak';        // 'peak'(식사시간 곡선) | 'knee'(계단 램프)
const PEAK    = BASE * MULT;                    // 목표 피크 세션 도착률(세션/s)

// 🔴 k6 의 arrival-rate `rate`/`startRate`/`target` 은 **정수만** 받는다.
//    baseline λ=0.4 세션/s 는 소수라 초당 단위로는 표현이 안 된다 → **분당(`timeUnit:'1m'`)** 으로 잡는다.
//    0.4/s = 24/min. 분당 정수 granularity = 0.0167 세션/s 라 baseline 도 충분히 표현된다.
const PEAK_PM = PEAK * 60;                      // 목표 피크 세션 도착률(세션/분)
const rpm = (f) => Math.max(1, Math.round(PEAK_PM * f));

// VU 예산: 세션 1회 ≈ 브라우징 3~5초 / 로그인 0.3초. 여유 6배.
const BROWSE_VUS_MAX = Number(__ENV.BROWSE_VUS_MAX || Math.max(40, Math.ceil(PEAK * 30)));
const LOGIN_VUS_MAX  = Number(__ENV.LOGIN_VUS_MAX  || Math.max(30, Math.ceil(PEAK * 12)));

const TERMS = ['김치','된장','불고기','비빔밥','제육','김밥','파스타','샐러드','계란','두부',
               '닭볶음','돼지고기','소고기','감자','고구마','미역','시금치','오이','당근','버섯',
               '떡볶이','순두부','미역국','김치찌개','된장찌개','볶음밥','카레','샌드위치','토마토','양파'];

// ── 램프 곡선 ────────────────────────────────────────────────────────────────
// peak: 식사시간 직전 집중을 모사 — 평시 → 30분전 → 직전 급상승 → 피크 고원 → 식사시작 급감.
//       (⚠️ 실제 시각을 맞출 필요 없음. 모방 대상은 '유입의 모양'이지 '시계'가 아니다.)
const PEAK_STAGES = [
  { target: rpm(0.25), duration: '60s' },   // 평시
  { target: rpm(0.60), duration: '60s' },   // 식사 30분 전
  { target: rpm(1.00), duration: '45s' },   // 식사 직전 급상승
  { target: rpm(1.00), duration: '90s' },   // 피크 고원 ★ 측정 구간
  { target: rpm(0.20), duration: '45s' },   // 식사 시작 → 급감
];
// knee: 단조 계단 — 각 단 45s 이상 유지(HPA 반응 ~60s 를 고려한 최소치). knee 를 넘으면 abortOnFail.
const KNEE_STAGES = [
  { target: rpm(0.10), duration: '45s' },
  { target: rpm(0.25), duration: '45s' },
  { target: rpm(0.50), duration: '45s' },
  { target: rpm(0.75), duration: '45s' },
  { target: rpm(1.00), duration: '60s' },
];
const STAGES = MODE === 'knee' ? KNEE_STAGES : PEAK_STAGES;

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  scenarios: {
    // 축1 — 새 세션 로그인 도착(account bcrypt). 세션 1개당 로그인 1회 = 가장 보수적 가정.
    peak_login: {
      executor: 'ramping-arrival-rate',
      startRate: rpm(0.05), timeUnit: '1m',
      preAllocatedVUs: Math.min(20, LOGIN_VUS_MAX), maxVUs: LOGIN_VUS_MAX,
      stages: STAGES, exec: 'sessionLogin',
    },
    // 축2 — 세션당 브라우징 버스트 10 req(홈·검색·상세·레시피북·팬트리·알림).
    peak_browse: {
      executor: 'ramping-arrival-rate',
      startRate: rpm(0.05), timeUnit: '1m',
      preAllocatedVUs: Math.min(30, BROWSE_VUS_MAX), maxVUs: BROWSE_VUS_MAX,
      stages: STAGES, exec: 'sessionBrowse',
    },
  },
  thresholds: {
    // ── SLO 판정(비중단 · 실패 시 k6 exit≠0 로 리포트만) ──
    'http_req_duration{name:login}':            ['p(95)<1000'],   // login < 1s
    'http_req_duration{name:recipe_search}':    ['p(95)<1000'],   // 검색/집계 < 1s
    'http_req_duration{name:hotdeals}':         ['p(95)<500'],    // 이하 단순조회 < 500ms
    'http_req_duration{name:recommend}':        ['p(95)<500'],
    'http_req_duration{name:budget}':           ['p(95)<500'],
    'http_req_duration{name:recipe_detail}':    ['p(95)<500'],
    'http_req_duration{name:recipe_reviews}':   ['p(95)<500'],
    'http_req_duration{name:book_list}':        ['p(95)<500'],
    'http_req_duration{name:mine_list}':        ['p(95)<500'],
    'http_req_duration{name:pantry_expiring}':  ['p(95)<500'],
    'http_req_duration{name:notifications}':    ['p(95)<500'],
    // ── 오류율 SLO(<1%) + 🔴 안전 킬스위치(>10% 면 중단) ──
    http_req_failed:   [
      'rate<0.01',
      { threshold: 'rate<0.10',  abortOnFail: true, delayAbortEval: '15s' },
    ],
    http_req_duration: [{ threshold: 'p(95)<3000', abortOnFail: true, delayAbortEval: '15s' }],
  },
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };
const sessionReqs = new Trend('session_browse_reqs');

function poolEmail(i) { return `loadtest-pool-${String(i).padStart(4, '0')}@mealbong.cloud`; }

// 브라우징 축이 쓸 토큰을 미리 확보(브라우징 자체가 로그인 비용에 오염되지 않게 분리).
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
  console.log(`setup: tokens=${tokens.length}/${n} · MODE=${MODE} · MULT=${MULT} · PEAK=${PEAK.toFixed(2)} 세션/s = ${rpm(1)} 세션/분 (≈${(PEAK * 11).toFixed(1)} req/s)`);
  return { tokens };
}

// ── 축1: 새 세션 로그인 ──────────────────────────────────────────────────────
export function sessionLogin() {
  const i = Math.floor(Math.random() * NUSERS) + 1;
  const r = http.post(`https://${HOST}/api/auth/login`,
    JSON.stringify({ email: poolEmail(i), password: PW }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login' } });
  check(r, { 'login 200': (res) => res.status === 200 });
}

// ── 축2: 1인가구 브라우징 버스트 ─────────────────────────────────────────────
// 페르소나 근거(docs/mp_k6_stage3_peak_viral.md §2): 퇴근길에 "오늘 뭐 싸지 → 그걸로 뭐 해먹지
// → 남은 예산 얼마 → 냉장고에 뭐 상해가지" 를 한 세션에 몰아 본다.
export function sessionBrowse(data) {
  const auth = { Authorization: `Bearer ${data.tokens[Math.floor(Math.random() * data.tokens.length)]}` };
  const q = TERMS[Math.floor(Math.random() * TERMS.length)];
  let n = 0;

  // ① 홈 — 오늘의 핫딜 + 추천 (price, Redis 캐시)
  check(http.get(`https://${HOST}/api/prices/hotdeals?limit=20`, { tags: { name: 'hotdeals' } }),
    { 'hotdeals 200': (r) => r.status === 200 }); n++;
  check(http.get(`https://${HOST}/api/prices/recommend?limit=20`, { tags: { name: 'recommend' } }),
    { 'recommend 200': (r) => r.status === 200 }); n++;
  sleep(0.3 + Math.random() * 0.4);

  // ② 남은 예산 (account)
  check(http.get(`https://${HOST}/api/users/budget`, { headers: auth, tags: { name: 'budget' } }),
    { 'budget 200': (r) => r.status === 200 }); n++;

  // ③ 레시피 검색 (recipe → ES `recipes_pgsync`)
  const s = http.get(`https://${HOST}/api/recipes?q=${encodeURIComponent(q)}`,
    { headers: auth, tags: { name: 'recipe_search' } }); n++;
  check(s, { 'recipe_search 200': (r) => r.status === 200 });
  sleep(0.3 + Math.random() * 0.5);

  // ④ 검색 결과 중 하나를 상세 + 리뷰 (recipe → PG)
  let rid = null;
  if (s.status === 200) {
    const list = s.json('recipes');
    if (list && list.length > 0) rid = list[Math.floor(Math.random() * list.length)].id;
  }
  if (rid !== null) {
    check(http.get(`https://${HOST}/api/recipes/${rid}`, { headers: auth, tags: { name: 'recipe_detail' } }),
      { 'recipe_detail 200': (r) => r.status === 200 }); n++;
    check(http.get(`https://${HOST}/api/recipes/${rid}/reviews`, { headers: auth, tags: { name: 'recipe_reviews' } }),
      { 'recipe_reviews 200': (r) => r.status === 200 }); n++;
  }
  sleep(0.2 + Math.random() * 0.4);

  // ⑤ 🔴 신규 측정 영역 — recipebook(내 레시피북 · 내가 등록한 레시피)
  check(http.get(`https://${HOST}/api/recipes/book`, { headers: auth, tags: { name: 'book_list' } }),
    { 'book_list 200': (r) => r.status === 200 }); n++;
  check(http.get(`https://${HOST}/api/recipes/mine`, { headers: auth, tags: { name: 'mine_list' } }),
    { 'mine_list 200': (r) => r.status === 200 }); n++;

  // ⑥ 🔴 신규 측정 영역 — pantry(소비기한 임박) · notify(알림)
  check(http.get(`https://${HOST}/api/pantry/expiring?within_days=3`, { headers: auth, tags: { name: 'pantry_expiring' } }),
    { 'pantry_expiring 200': (r) => r.status === 200 }); n++;
  check(http.get(`https://${HOST}/api/notifications?limit=20`, { headers: auth, tags: { name: 'notifications' } }),
    { 'notifications 200': (r) => r.status === 200 }); n++;

  sessionReqs.add(n);
}
