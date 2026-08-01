// Stage1 — account 로그인 knee 탐색 (35/s는 흡수됐으니 그 위로)
// 목적: 4 replica(max)가 실제 포화(throttle)돼 p95가 무너지는 지점 = knee 찾기.
//       CPU가 pod limit(~2core)에서 plateau + p95 상승 = 포화 신호.
//
// 실행: cp loadtest/stage1_account_knee.js /mnt/c/temp/ &&
//        /mnt/c/temp/k6.exe run -e N=50 'C:\temp\stage1_account_knee.js'
//
// 안전: 30→90 logins/s. p95>5s 또는 오류>10% 면 k6 자동 중단(=knee 살짝 지나면 멈춤).
//       라이브 로그인이 이 구간에서 느려질 수 있음(off-peak).

import http from 'k6/http';
import { check } from 'k6';

const IP   = __ENV.IP   || '192.168.0.14';
const HOST = __ENV.HOST || 'app.mealbong.cloud';
const N    = Number(__ENV.N || 50);
const PW   = __ENV.PW   || 'LoadTest2026!';

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  scenarios: {
    login: {
      executor: 'ramping-arrival-rate',
      startRate: 30,
      timeUnit: '1s',
      preAllocatedVUs: 60,
      maxVUs: 300,               // 지연 커져도 도착률 유지되게 넉넉히
      stages: [
        { target: 45, duration: '25s' },
        { target: 60, duration: '30s' },
        { target: 75, duration: '30s' },
        { target: 90, duration: '30s' },   // knee 넘으면 abortOnFail이 끊음
      ],
    },
  },
  thresholds: {
    http_req_failed:   [{ threshold: 'rate<0.10',  abortOnFail: true, delayAbortEval: '10s' }],
    http_req_duration: [{ threshold: 'p(95)<5000', abortOnFail: true, delayAbortEval: '10s' }],
  },
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };

export default function () {
  const i = Math.floor(Math.random() * N) + 1;
  const email = `loadtest-pool-${String(i).padStart(4, '0')}@mealbong.cloud`;
  const r = http.post(`https://${HOST}/api/auth/login`,
    JSON.stringify({ email, password: PW }), JSON_H);
  check(r, { 'login 200': (res) => res.status === 200 });
}
