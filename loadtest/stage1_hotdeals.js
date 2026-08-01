// Stage1 하네스 셰이크아웃 — hotdeals (인증 불필요 + Redis 캐시 = 저위험)
// 목적: ramping-arrival-rate executor + abortOnFail 임계값 + 관측 게이트가 실제로 도는지 검증.
//       (price 서비스 부하지만 캐시라 경미 — 진짜 knee 탐색 아님, 하네스 검증용)
//
// 실행(Windows k6.exe via WSL interop):
//   cp loadtest/stage1_hotdeals.js /mnt/c/temp/ && /mnt/c/temp/k6.exe run 'C:\temp\stage1_hotdeals.js'
//
// 안전: 최대 50 rps·80초 유한 런. 오류율>5% 또는 p95>1s 면 k6가 스스로 중단(abortOnFail).

import http from 'k6/http';
import { check } from 'k6';

const IP   = __ENV.IP   || '192.168.0.14';
const HOST = __ENV.HOST || 'app.mealbong.cloud';

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  scenarios: {
    hotdeals: {
      executor: 'ramping-arrival-rate',
      startRate: 5,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 100,
      stages: [
        { target: 10, duration: '20s' },   // 5 → 10 rps
        { target: 25, duration: '20s' },   // 10 → 25 rps
        { target: 50, duration: '20s' },   // 25 → 50 rps
        { target: 50, duration: '20s' },   // 50 rps 고원
      ],
    },
  },
  thresholds: {
    // 안전 킬스위치 — 넘으면 k6가 즉시 중단(사람 감시 불필요)
    http_req_failed:   [{ threshold: 'rate<0.05',   abortOnFail: true, delayAbortEval: '10s' }],
    http_req_duration: [{ threshold: 'p(95)<1000',  abortOnFail: true, delayAbortEval: '10s' }],
  },
};

export default function () {
  const r = http.get(`https://${HOST}/api/prices/hotdeals?limit=20`);
  check(r, { 'hotdeals 200': (res) => res.status === 200 });
}
