// Stage1 — account /refresh 램프 (현실 fan-out 재현 · "병목 없음" 못박기)
// 목적: 알림 fan-out 의 실제 경로는 /login(bcrypt 200ms)이 아니라 /refresh(JWT 검증 µs)다.
//       프론트(api.ts)는 access(30분) 만료 시 refresh_token(14일)으로 silent 재발급 → /login 안 감.
//       그래서 login knee(≈50/s)보다 훨씬 높은 레이트에서도 /refresh 는 p95 가 평평해야 한다.
//       (로컬 실측: /refresh ≈ 67µs/건 = 코어당 ~15,000/s vs /login 5/s — 약 3000배.)
//
// 대조군: stage1_account_login.js (같은 규모에서 35/s 근처 knee). 이 스크립트는 그 위로 램프해도 안 죽음을 본다.
//
// 선행: seed_users.js 로 유저 풀(N개) 시드.
// 실행: cp loadtest/stage1_account_refresh.js /mnt/c/temp/ &&
//        /mnt/c/temp/k6.exe run -e N=50 'C:\temp\stage1_account_refresh.js'
//
// 안전: 램프 20→400 /s · ~2.5분 유한 런. 오류율>10% 또는 p95>2s 면 자동 중단(abortOnFail).

import http from 'k6/http';
import { check, fail } from 'k6';

const IP   = __ENV.IP   || '192.168.0.14';
const HOST = __ENV.HOST || 'app.mealbong.cloud';
const N    = Number(__ENV.N || 50);
const PW   = __ENV.PW   || 'LoadTest2026!';

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  scenarios: {
    refresh: {
      executor: 'ramping-arrival-rate',
      startRate: 20,
      timeUnit: '1s',
      preAllocatedVUs: 50,
      maxVUs: 300,
      stages: [
        { target: 50,  duration: '20s' },   // login 이 knee 나던 지점 — 여기선 평평해야
        { target: 150, duration: '40s' },
        { target: 300, duration: '40s' },
        { target: 400, duration: '40s' },    // fan-out 규모를 한참 넘겨도 여유
      ],
    },
  },
  thresholds: {
    // /login 대비 훨씬 빡빡하게 — bcrypt 가 없으니 이 정도는 우습게 지켜야 "병목 없음"이 증명됨
    http_req_failed:   [{ threshold: 'rate<0.10',  abortOnFail: true, delayAbortEval: '10s' }],
    http_req_duration: [{ threshold: 'p(95)<2000', abortOnFail: true, delayAbortEval: '10s' }],
  },
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };

// setup: 풀 유저를 한 번씩 로그인해 refresh 토큰을 모은다(여기서만 bcrypt 비용 발생·1회성).
// /refresh 는 스테이트리스(토큰 회전 없음)라 이 토큰들을 런 내내 재사용해도 된다.
export function setup() {
  const tokens = [];
  for (let i = 1; i <= N; i++) {
    const email = `loadtest-pool-${String(i).padStart(4, '0')}@mealbong.cloud`;
    const r = http.post(`https://${HOST}/api/auth/login`,
      JSON.stringify({ email, password: PW }), JSON_H);
    if (r.status === 200) {
      const rt = r.json('refresh_token');
      if (rt) tokens.push(rt);
    }
  }
  if (tokens.length === 0) {
    fail('refresh 토큰을 하나도 못 얻음 — seed_users.js 로 풀을 먼저 시드했는지 확인');
  }
  return { tokens };
}

export default function (data) {
  const rt = data.tokens[Math.floor(Math.random() * data.tokens.length)];
  const r = http.post(`https://${HOST}/api/auth/refresh`,
    JSON.stringify({ refresh_token: rt }), JSON_H);
  check(r, { 'refresh 200': (res) => res.status === 200 });
}
