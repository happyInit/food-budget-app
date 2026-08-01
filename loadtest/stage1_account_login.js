// Stage1 — account 로그인 램프 (진짜 HPA 테스트 · 구 P0 bcrypt CPU 포화 재현)
// 목적: mp-account HPA(70%/2~4)가 로그인 부하를 흡수하나 — 스케일 2→4·knee·반응 gap 관측.
//
// 선행: seed_users.js 로 유저 풀(N개) 시드.
// 실행: cp loadtest/stage1_account_login.js /mnt/c/temp/ &&
//        /mnt/c/temp/k6.exe run -e N=50 'C:\temp\stage1_account_login.js'
//
// 안전: 램프 2→35 logins/s · ~2.3분 유한 런. 오류율>10% 또는 p95>5s 면 k6 자동 중단(abortOnFail).
//       라이브 로그인 경로라 knee까지만 보고 위험 전에 끊는다.

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
      startRate: 2,
      timeUnit: '1s',
      preAllocatedVUs: 30,
      maxVUs: 120,
      stages: [
        { target: 3,  duration: '20s' },   // 워밍
        { target: 8,  duration: '30s' },
        { target: 15, duration: '30s' },
        { target: 25, duration: '30s' },
        { target: 35, duration: '30s' },   // 여기서 knee/HPA 스케일 보일 것
      ],
    },
  },
  thresholds: {
    // knee까지는 관측, 위험 전에 자동 중단
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
