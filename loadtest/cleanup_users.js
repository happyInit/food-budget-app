// 테스트 유저 정리 — loadtest-pool-0001..N + loadtest-smoke 삭제 (login → DELETE /api/users/me)
// 실행: cp loadtest/cleanup_users.js /mnt/c/temp/ && /mnt/c/temp/k6.exe run -e N=50 'C:\temp\cleanup_users.js'
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';

const IP   = __ENV.IP   || '192.168.0.14';
const HOST = __ENV.HOST || 'app.mealbong.cloud';
const PW   = __ENV.PW   || 'LoadTest2026!';
const N    = Number(__ENV.N || 50);

export const options = {
  hosts: { [HOST]: IP },
  insecureSkipTLSVerify: true,
  vus: 5,
  iterations: N + 1,   // pool N + smoke 1
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };

export default function () {
  const i = exec.scenario.iterationInTest;
  const email = i < N
    ? `loadtest-pool-${String(i + 1).padStart(4, '0')}@mealbong.cloud`
    : 'loadtest-smoke@mealbong.cloud';

  const lo = http.post(`https://${HOST}/api/auth/login`,
    JSON.stringify({ email, password: PW }), JSON_H);
  if (lo.status !== 200) {
    check(lo, { '이미 없음(로그인 실패=삭제됨)': (r) => r.status === 401 });
    return;
  }
  const token = lo.json('access_token');
  const del = http.del(`https://${HOST}/api/users/me`, null,
    { headers: { Authorization: `Bearer ${token}` } });
  check(del, { '삭제 204/404': (r) => r.status === 204 || r.status === 404 });
}
