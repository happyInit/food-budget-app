// Stage1 — recipe 검색 램프 (ES 직격 · 캐시 안 먹는 고유 쿼리)
// 목적: account와 다른 병목축(ES) — 고카디널리티 검색이 ES throughput을 어디서 포화시키나.
//
// 실행: cp loadtest/stage1_recipe_search.js /mnt/c/temp/ &&
//        /mnt/c/temp/k6.exe run 'C:\temp\stage1_recipe_search.js'
//
// 안전: 10→100 req/s. p95>3s(검색 SLO 1s 넘어 관측 여유) 또는 오류>10% 면 자동 중단.

import http from 'k6/http';
import { check } from 'k6';

const IP   = __ENV.IP   || '192.168.0.14';
const HOST = __ENV.HOST || 'app.mealbong.cloud';
const PW   = __ENV.PW   || 'LoadTest2026!';

// 흔한 한식 검색어 — 다양성 확보로 앱/ES 캐시 편향 완화
const TERMS = ['김치','된장','불고기','비빔밥','제육','김밥','파스타','샐러드','계란','두부',
               '닭볶음','돼지고기','소고기','감자','고구마','미역','시금치','오이','당근','버섯',
               '떡볶이','순두부','미역국','김치찌개','된장찌개','볶음밥','카레','샌드위치','토마토','양파'];

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  scenarios: {
    search: {
      executor: 'ramping-arrival-rate',
      startRate: 5,
      timeUnit: '1s',
      preAllocatedVUs: 40,
      maxVUs: 200,
      stages: [
        { target: 10,  duration: '20s' },
        { target: 30,  duration: '30s' },
        { target: 60,  duration: '30s' },
        { target: 100, duration: '30s' },
      ],
    },
  },
  thresholds: {
    http_req_failed:   [{ threshold: 'rate<0.10',  abortOnFail: true, delayAbortEval: '10s' }],
    http_req_duration: [{ threshold: 'p(95)<3000', abortOnFail: true, delayAbortEval: '10s' }],
  },
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };

// 인증 필요할 수 있어 토큰 확보(불필요해도 무해)
export function setup() {
  const lo = http.post(`https://${HOST}/api/auth/login`,
    JSON.stringify({ email: 'loadtest-pool-0001@mealbong.cloud', password: PW }), JSON_H);
  return { token: lo.status === 200 ? lo.json('access_token') : null };
}

export default function (data) {
  const q = TERMS[Math.floor(Math.random() * TERMS.length)];
  const params = data.token ? { headers: { Authorization: `Bearer ${data.token}` } } : {};
  const r = http.get(`https://${HOST}/api/recipes?q=${encodeURIComponent(q)}`, params);
  check(r, { 'recipes 200': (res) => res.status === 200 });
}
