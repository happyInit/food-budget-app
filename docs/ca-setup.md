# 로컬 CA 설치 매뉴얼 (WSL Ubuntu)

> Harbor·Grafana가 **로컬 CA로 HTTPS**를 씁니다. 담당자에게 받은 **`ca.crt` 한 개**만 아래대로 신뢰시키면 끝.
> `ca.crt`는 공개 인증서라 메신저로 받아도 안전합니다. (비밀은 `*.key`뿐 — 공유 금지)

## 0. 준비
받은 `ca.crt`를 WSL 홈에 저장 (예: `~/ca.crt`).

## 1. 시스템 신뢰 — curl/CLI용 (모두)
```bash
sudo cp ~/ca.crt /usr/local/share/ca-certificates/fb-local-ca.crt
sudo update-ca-certificates
# 확인 (healthy 나오면 성공)
curl https://192.168.0.10/api/v2.0/health
```

## 2. Docker 신뢰 — Harbor push/pull 할 사람만
```bash
sudo mkdir -p /etc/docker/certs.d/192.168.0.10
sudo cp ~/ca.crt /etc/docker/certs.d/192.168.0.10/ca.crt
# docker 재시작 불필요
docker login 192.168.0.10        # HTTPS로 로그인·push 됨
```
> Docker Desktop + WSL 통합을 쓰면: **3번(Windows)** 에 CA 신뢰 후 Docker Desktop **재시작**으로도 됩니다.

## 3. 브라우저 UI — Grafana/Harbor 화면 볼 때
WSL 유저도 브라우저는 **Windows** 것이라, UI 경고는 Windows에서 처리:
- **간단**: 경고 화면에서 "고급 → 계속 진행" (간이 프로젝트면 이걸로 OK)
- **경고 제거**: `ca.crt`를 Windows에 설치
  1. WSL→Windows로 파일 꺼내기: `cp ~/ca.crt /mnt/c/Users/<윈도우사용자>/Downloads/`
  2. Downloads의 `ca.crt` 더블클릭 → 인증서 설치 → **현재 사용자** → "신뢰할 수 있는 루트 인증 기관"
  3. (Firefox는 별도) 설정 → 인증서 보기 → 인증 기관 → 가져오기 → ca.crt

## 접속 주소
| 서비스 | 주소 |
|---|---|
| Harbor | https://192.168.0.10 (admin / 담당자에게) |
| Grafana | https://192.168.0.11:3000 |

## (선택) 진위 확인
메신저 전송이 못 미더우면 지문을 담당자 값과 대조:
```bash
openssl x509 -in ~/ca.crt -noout -fingerprint -sha256
```

---

*요약: `ca.crt` → **①시스템 신뢰(모두)** → **②docker certs.d(push하는 사람)** → **③Windows 신뢰(브라우저용)**. 끝.*
