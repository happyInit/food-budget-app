// Stage2 — 유저 축: price 캐시 읽기 부하 (hotdeals + recommend)
// matview refresh가 이 캐시를 flush → 미스 폭증(스탬피드) + PG REFRESH 경합이 여기 드러남.
// 인증 불필요(공개 GET).
//
// 실행: cp loadtest/stage2_price_load.js /mnt/c/temp/ &&
//        /mnt/c/temp/k6.exe run -e RATE=200 -e DUR=120s 'C:\temp\stage2_price_load.js'
//
// 안전: 오류>10% 또는 p95>3s 면 자동 중단.

import http from 'k6/http';
import { check } from 'k6';

const IP   = __ENV.IP   || '192.168.0.14';
const HOST = __ENV.HOST || 'app.mealbong.cloud';
const RATE = Number(__ENV.RATE || 200);

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  scenarios: {
    price: {
      executor: 'constant-arrival-rate',
      rate: RATE, timeUnit: '1s', duration: (__ENV.DUR || '120s'),
      preAllocatedVUs: 50, maxVUs: 300,
    },
  },
  thresholds: {
    'http_req_duration{name:hotdeals}':  ['p(95)<2000'],
    'http_req_duration{name:recommend}': ['p(95)<2000'],
    http_req_failed:   [{ threshold: 'rate<0.10',  abortOnFail: true, delayAbortEval: '15s' }],
    http_req_duration: [{ threshold: 'p(95)<3000', abortOnFail: true, delayAbortEval: '15s' }],
  },
};

export default function () {
  if (Math.random() < 0.5) {
    const r = http.get(`https://${HOST}/api/prices/hotdeals?limit=20`, { tags: { name: 'hotdeals' } });
    check(r, { 'hotdeals 200': (res) => res.status === 200 });
  } else {
    const r = http.get(`https://${HOST}/api/prices/recommend?limit=20`, { tags: { name: 'recommend' } });
    check(r, { 'recommend 200': (res) => res.status === 200 });
  }
}
