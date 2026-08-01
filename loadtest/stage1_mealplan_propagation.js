// Stage1 — mealplan HPA-무용 검증 (다운스트림 전파)
// 가설: mealplan/cart는 account budget API를 호출 → account가 바쁘면 cart도 느려진다.
//       그런데 mealplan 자체 CPU는 낮음 → mealplan replica를 늘려도 소용없다(HPA-무용).
//
// 구성: 두 시나리오 동시 —
//   account_pressure: 로그인 40/s (account bcrypt 압박)
//   mealplan_victim : cart 15/s (account budget 대기 → 전파 피해자)
//
// 실행: cp loadtest/stage1_mealplan_propagation.js /mnt/c/temp/ &&
//        /mnt/c/temp/k6.exe run 'C:\temp\stage1_mealplan_propagation.js'
//
// 볼 것: cart p95↑ 인데 mealplan pod CPU는 낮게 유지 = HPA-무용 증거.

import http from 'k6/http';
import { check } from 'k6';

const IP   = __ENV.IP   || '192.168.0.14';
const HOST = __ENV.HOST || 'app.mealbong.cloud';
const PW   = __ENV.PW   || 'LoadTest2026!';
const N    = Number(__ENV.NUSERS || 50);

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  scenarios: {
    account_pressure: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.PRESS || 40), timeUnit: '1s', duration: (__ENV.DUR || '80s'),
      preAllocatedVUs: 80, maxVUs: 350, exec: 'pressureLogin',
    },
    mealplan_victim: {
      executor: 'constant-arrival-rate',
      rate: 15, timeUnit: '1s', duration: (__ENV.DUR || '80s'), startTime: '10s',
      preAllocatedVUs: 30, maxVUs: 120, exec: 'cartCall',
    },
  },
  thresholds: {
    'http_req_duration{name:cart}':  ['p(95)<8000'],   // 관측용(전파 피해)
    'http_req_duration{name:login}': ['p(95)<8000'],
    http_req_failed:   [{ threshold: 'rate<0.15',  abortOnFail: true, delayAbortEval: '15s' }],
    http_req_duration: [{ threshold: 'p(95)<6000', abortOnFail: true, delayAbortEval: '15s' }],
  },
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };

export function setup() {
  const lo = http.post(`https://${HOST}/api/auth/login`,
    JSON.stringify({ email: 'loadtest-pool-0001@mealbong.cloud', password: PW }), JSON_H);
  return { token: lo.status === 200 ? lo.json('access_token') : null };
}

// account 압박 — 로그인(bcrypt)
export function pressureLogin() {
  const u = Math.floor(Math.random() * N) + 1;
  const email = `loadtest-pool-${String(u).padStart(4, '0')}@mealbong.cloud`;
  const r = http.post(`https://${HOST}/api/auth/login`,
    JSON.stringify({ email, password: PW }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login' } });
  check(r, { 'login 200': (res) => res.status === 200 });
}

// 피해자 — cart(내부에서 account budget 호출)
export function cartCall(data) {
  const r = http.get(`https://${HOST}/api/mealplan/cart`,
    { headers: { Authorization: `Bearer ${data.token}` }, tags: { name: 'cart' } });
  check(r, { 'cart 200': (res) => res.status === 200 });
}
