// Stage1 — "동시 N명" 혼합 저니 (closed model / ramping-vus)
// 각 VU = 동시접속 유저 1명: 로그인(1회) → [레시피 검색 + 핫딜 + 예산조회] 반복 + think-time.
// 500명 기준으로 돌리고, 넉넉하면 VUS 올려서 재실행.
//
// 실행: cp loadtest/stage1_journey.js /mnt/c/temp/ &&
//        /mnt/c/temp/k6.exe run -e VUS=500 -e NUSERS=500 'C:\temp\stage1_journey.js'
//
// 선행: seed_users.js 로 NUSERS 만큼 유저 풀 시드.
// 안전: 전체 p95>3s 또는 오류>10% 면 자동 중단(abortOnFail).

import http from 'k6/http';
import { check, sleep } from 'k6';

const IP     = __ENV.IP   || '192.168.0.14';
const HOST   = __ENV.HOST || 'app.mealbong.cloud';
const PW     = __ENV.PW   || 'LoadTest2026!';
const VUS    = Number(__ENV.VUS    || 500);   // 동시접속 유저 수
const NUSERS = Number(__ENV.NUSERS || 500);   // 시드된 유저 풀 크기

const TERMS = ['김치','된장','불고기','비빔밥','제육','김밥','파스타','샐러드','계란','두부',
               '닭볶음','돼지고기','소고기','감자','고구마','미역','시금치','오이','당근','버섯',
               '떡볶이','순두부','미역국','김치찌개','된장찌개','볶음밥','카레','샌드위치','토마토','양파'];

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  scenarios: {
    journey: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { target: VUS, duration: '30s' },   // 유입(로그인 버스트)
        { target: VUS, duration: '90s' },   // 고원: 동시 VUS명 유지
        { target: 0,   duration: '15s' },   // 정리
      ],
    },
  },
  thresholds: {
    // 엔드포인트별 p95 (요약에 표시)
    'http_req_duration{name:login}':         ['p(95)<2000'],
    'http_req_duration{name:recipe_search}': ['p(95)<2000'],
    'http_req_duration{name:hotdeals}':      ['p(95)<1000'],
    'http_req_duration{name:budget}':        ['p(95)<1000'],
    // 안전 킬스위치
    http_req_failed:   [{ threshold: 'rate<0.10',  abortOnFail: true, delayAbortEval: '15s' }],
    http_req_duration: [{ threshold: 'p(95)<3000', abortOnFail: true, delayAbortEval: '15s' }],
  },
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };
let token = null;   // VU 스코프 — 각 VU 로그인 1회

function login() {
  const u = ((__VU - 1) % NUSERS) + 1;
  const email = `loadtest-pool-${String(u).padStart(4, '0')}@mealbong.cloud`;
  const r = http.post(`https://${HOST}/api/auth/login`,
    JSON.stringify({ email, password: PW }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login' } });
  return r.status === 200 ? r.json('access_token') : null;
}

export default function () {
  if (!token) token = login();
  const auth = token ? { Authorization: `Bearer ${token}` } : {};

  const q = TERMS[Math.floor(Math.random() * TERMS.length)];
  const r1 = http.get(`https://${HOST}/api/recipes?q=${encodeURIComponent(q)}`,
    { headers: auth, tags: { name: 'recipe_search' } });
  const r2 = http.get(`https://${HOST}/api/prices/hotdeals?limit=20`,
    { tags: { name: 'hotdeals' } });
  const r3 = http.get(`https://${HOST}/api/users/budget`,
    { headers: auth, tags: { name: 'budget' } });

  check(r1, { 'recipe 200': (r) => r.status === 200 });
  check(r2, { 'hotdeals 200': (r) => r.status === 200 });
  check(r3, { 'budget 200': (r) => r.status === 200 });

  sleep(Math.random() * 2 + 1);   // think-time 1~3초
}
