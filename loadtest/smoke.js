// k6 스모크 — 부하테스트 사전 검증 (1회 왕복)
// 목적: LAN에서 Gateway(.14) 직타 도달 + 로그인→토큰→인증 GET 이 되는지 확인.
//       여기가 통과해야 Stage1 포화 스윕을 짤 수 있다.
//
// 실행:  k6 run loadtest/smoke.js
//   덮어쓰기: k6 run -e IP=192.168.0.14 -e EMAIL=you@x.com -e PASSWORD=... loadtest/smoke.js
//
// 주의:
//  · signup 은 account DB 에 유저 1건을 실제로 만든다(무해하지만 테스트 계정으로 표시).
//  · .14 는 IP 라 hosts 로 SNI/Host=app.mealbong.cloud 를 주입(curl --resolve 와 동일) → CF 터널 우회.
//  · insecureSkipTLSVerify 는 스모크 한정(오리진 인증서 체인 검증 생략). Stage1 에선 재검토.

import http from 'k6/http';
import { check } from 'k6';

const IP    = __ENV.IP       || '192.168.0.14';
const HOST  = __ENV.HOST     || 'app.mealbong.cloud';
const EMAIL = __ENV.EMAIL    || 'loadtest-smoke@mealbong.cloud';
const PW    = __ENV.PASSWORD || 'LoadTest2026!';
const NICK  = __ENV.NICK     || 'k6-smoke';

const BASE = `https://${HOST}`;   // hosts 로 .14 에 매핑 → SNI/Host 는 도메인, 다이얼은 IP

export const options = {
  hosts: { [HOST]: IP },          // curl --resolve 와 동일: 도메인 → .14
  insecureSkipTLSVerify: true,    // 스모크 한정
  vus: 1,
  iterations: 1,
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };

export default function () {
  // ① signup (이미 있으면 409 → 정상, 로그인으로 진행)
  const su = http.post(`${BASE}/api/auth/signup`,
    JSON.stringify({ email: EMAIL, password: PW, nickname: NICK }), JSON_H);
  check(su, { '① signup 201 or 409(기존)': (r) => r.status === 201 || r.status === 409 });

  // ② login → access_token
  const lo = http.post(`${BASE}/api/auth/login`,
    JSON.stringify({ email: EMAIL, password: PW }), JSON_H);
  check(lo, { '② login 200': (r) => r.status === 200 });
  const token = lo.status === 200 ? lo.json('access_token') : null;
  check(token, { '③ access_token 발급': (t) => !!t });

  // ③ 인증 GET — 토큰이 실제로 통해야 200
  const me = http.get(`${BASE}/api/users/me`,
    { headers: { Authorization: `Bearer ${token}` } });
  check(me, { '④ /api/users/me 200': (r) => r.status === 200 });

  console.log(`signup=${su.status} login=${lo.status} me=${me.status} me_body=${me.body}`);
}
