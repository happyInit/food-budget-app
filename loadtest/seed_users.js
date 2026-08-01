// 테스트 유저 풀 시드 — account 로그인 램프용 다수 계정 생성 (멱등: 201 또는 409)
// 실행: cp loadtest/seed_users.js /mnt/c/temp/ && /mnt/c/temp/k6.exe run -e N=50 'C:\temp\seed_users.js'
//
// 계정 규약: loadtest-pool-0001@mealbong.cloud .. (비번 공통) — 램프 스크립트와 동일 규약.
// 주의: account DB에 테스트 유저 N건 생성(테스트 계정, 나중 정리 필요).

import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';

const IP   = __ENV.IP   || '192.168.0.14';
const HOST = __ENV.HOST || 'app.mealbong.cloud';
const N    = Number(__ENV.N || 50);
const PW   = __ENV.PW   || 'LoadTest2026!';

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  vus: 5,
  iterations: N,           // 총 N개 생성 (shared-iterations)
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };

export default function () {
  const i = exec.scenario.iterationInTest + 1;   // 전역 고유 1..N
  const email = `loadtest-pool-${String(i).padStart(4, '0')}@mealbong.cloud`;
  const r = http.post(`https://${HOST}/api/auth/signup`,
    JSON.stringify({ email, password: PW, nickname: `lt-pool-${i}` }), JSON_H);
  check(r, { 'signup 201/409(기존)': (res) => res.status === 201 || res.status === 409 });
}
