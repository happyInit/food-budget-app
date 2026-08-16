// Stage1 — "동시 N명" 혼합 저니 (closed model / ramping-vus)
// 각 VU = 동시접속 유저 1명: 로그인(1회) → [레시피 검색 + 핫딜 + 예산조회] 반복 + think-time.
// 500명 기준으로 돌리고, 넉넉하면 VUS 올려서 재실행.
//
// 실행(온프렘): cp loadtest/stage1_journey.js /mnt/c/temp/ &&
//        /mnt/c/temp/k6.exe run -e VUS=500 -e NUSERS=500 'C:\temp\stage1_journey.js'
// 실행(AWS)   : loadtest/run_aws_stage1.sh 참조 (IP=none · HOST=aws.mealbong.cloud)
//
// 선행: seed_users.js 로 NUSERS 만큼 유저 풀 시드.
// 안전: 전체 p95>3s 또는 오류>10% 면 자동 중단(abortOnFail).

import http from 'k6/http';
import { check, sleep } from 'k6';

// 🔴 IP='none' 이면 hosts 고정을 끄고 **실DNS** 를 쓴다 — AWS 전용 스위치다.
//    온프렘은 MetalLB VIP `.14` 단일이라 고정이 맞지만, AWS 는 ALB 가 **AZ 당 하나씩 IP 2개**를
//    돌려준다. 한 IP 로 고정하면 부하가 **AZ 한쪽에만** 몰려서, 우리가 측정하려는
//    "2 AZ 로 분산된 클러스터"가 아니라 "AZ 한 개"를 측정하게 된다.
//    ⚠️ 기본값은 온프렘 `.14` 그대로다 — 기존 실행 방법을 바꾸지 않는다.
const IP     = __ENV.IP   || '192.168.0.14';
const PIN_IP = IP !== 'none';
const HOST   = __ENV.HOST || 'app.mealbong.cloud';
const PW     = __ENV.PW   || 'LoadTest2026!';
const VUS    = Number(__ENV.VUS    || 500);   // 동시접속 유저 수
const NUSERS = Number(__ENV.NUSERS || 500);   // 시드된 유저 풀 크기

// 구간 길이. 🔴 **Karpenter 를 보려면 고원(PLATEAU)이 길어야 한다** — 노드 프로비저닝은
//    EC2 기동 + 부트스트랩 + 조인까지 60~90초가 걸린다. 기본 90s 고원이면 노드가 Ready 가 되는
//    순간 시험이 끝나서 "NodeClaim 은 생겼는데 처리량은 안 늘었다"는 결과가 나온다(측정 실패).
//    ⇒ Karpenter 시험은 PLATEAU=6m 이상으로 준다. 기본값은 종전과 동일해 기존 실행을 안 바꾼다.
const RAMP    = __ENV.RAMP    || '30s';
const PLATEAU = __ENV.PLATEAU || '90s';
const RAMPDN  = __ENV.RAMPDN  || '15s';

const TERMS = ['김치','된장','불고기','비빔밥','제육','김밥','파스타','샐러드','계란','두부',
               '닭볶음','돼지고기','소고기','감자','고구마','미역','시금치','오이','당근','버섯',
               '떡볶이','순두부','미역국','김치찌개','된장찌개','볶음밥','카레','샌드위치','토마토','양파'];

export const options = {
  hosts: PIN_IP ? { [HOST]: IP } : {},
  insecureSkipTLSVerify: true,
  scenarios: {
    journey: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { target: VUS, duration: RAMP },      // 유입(로그인 버스트)
        { target: VUS, duration: PLATEAU },   // 고원: 동시 VUS명 유지
        { target: 0,   duration: RAMPDN },    // 정리
      ],
    },
  },
  thresholds: {
    // 엔드포인트별 p95 (요약에 표시)
    'http_req_duration{name:login}':         ['p(95)<2000'],
    'http_req_duration{name:recipe_search}': ['p(95)<2000'],
    'http_req_duration{name:hotdeals}':      ['p(95)<1000'],
    'http_req_duration{name:budget}':        ['p(95)<1000'],
    // 안전 킬스위치
    http_req_failed:   [{ threshold: 'rate<0.10',  abortOnFail: true, delayAbortEval: '15s' }],
    http_req_duration: [{ threshold: 'p(95)<3000', abortOnFail: true, delayAbortEval: '15s' }],
  },
};

const JSON_H = { headers: { 'Content-Type': 'application/json' } };
let token = null;   // VU 스코프 — 각 VU 로그인 1회

function login() {
  const u = ((__VU - 1) % NUSERS) + 1;
  const email = `loadtest-pool-${String(u).padStart(4, '0')}@mealbong.cloud`;
  const r = http.post(`https://${HOST}/api/auth/login`,
    JSON.stringify({ email, password: PW }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'login' } });
  return r.status === 200 ? r.json('access_token') : null;
}

export default function () {
  if (!token) token = login();
  const auth = token ? { Authorization: `Bearer ${token}` } : {};

  const q = TERMS[Math.floor(Math.random() * TERMS.length)];
  const r1 = http.get(`https://${HOST}/api/recipes?q=${encodeURIComponent(q)}`,
    { headers: auth, tags: { name: 'recipe_search' } });
  const r2 = http.get(`https://${HOST}/api/prices/hotdeals?limit=20`,
    { tags: { name: 'hotdeals' } });
  const r3 = http.get(`https://${HOST}/api/users/budget`,
    { headers: auth, tags: { name: 'budget' } });

  check(r1, { 'recipe 200': (r) => r.status === 200 });
  check(r2, { 'hotdeals 200': (r) => r.status === 200 });
  check(r3, { 'budget 200': (r) => r.status === 200 });

  sleep(Math.random() * 2 + 1);   // think-time 1~3초
}
