#!/bin/sh
# Lightsail 최초 부팅 스크립트 — 호스트 준비까지만 한다.
# 스택 기동은 .env(시크릿)가 필요하므로 사람이 SSH 로 들어와서 한다.
#
# 🔴 반드시 POSIX sh 로 쓴다. Lightsail 은 이 내용을 자기 헤더(`#!/bin/sh`) 뒤에 이어붙여
#    dash 로 실행하므로 셔뱅이 무시된다. `set -o pipefail`, `> >(tee ...)` 같은 bash 전용
#    문법을 쓰면 cloud-init 이 "Illegal option -o pipefail" 로 죽고 부팅 준비가 통째로 안 된다
#    (2026-08-30 실제로 겪음).
set -eux
exec >> /var/log/mp-userdata.log 2>&1

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg git jq unzip

# ── Docker (공식 저장소) ─────────────────────────────────────────────────────
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker ubuntu

# 로그가 80GB 디스크를 갉아먹지 않도록 데몬 기본값으로도 한 번 더 막는다
cat > /etc/docker/daemon.json <<'JSON'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
JSON
systemctl restart docker

# ── AWS CLI v2 (시드 내려받기·백업 업로드) ──────────────────────────────────
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscli.zip
unzip -q /tmp/awscli.zip -d /tmp && /tmp/aws/install && rm -rf /tmp/aws /tmp/awscli.zip

# ── 스왑 2GB ────────────────────────────────────────────────────────────────
# 4 GiB 호스트에 실사용 2.9 GiB. 여유가 1 GiB 남지만 빌드 중 순간 피크를 흡수할 안전판이 필요하다.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10
  echo 'vm.swappiness=10' > /etc/sysctl.d/99-mp-swap.conf
fi

# ── 🔴 Elasticsearch 필수 커널 파라미터 ─────────────────────────────────────
# 이게 없으면 ES 컨테이너가 부트스트랩 체크에서 죽는다("max virtual memory areas too low").
sysctl -w vm.max_map_count=262144
echo 'vm.max_map_count=262144' > /etc/sysctl.d/99-mp-elasticsearch.conf

# ── 레포 ────────────────────────────────────────────────────────────────────
# GitLab(gitlab.mealbong.cloud)은 철거된다. 정본 사본은 GitHub 에 있다(브랜치 전량 동기화 확인됨).
sudo -u ubuntu git clone --depth 1 https://github.com/happyInit/food-budget-app.git /home/ubuntu/app

# ── 부팅 시 스택 자동 기동 ──────────────────────────────────────────────────
cat > /etc/systemd/system/mealplanning.service <<'UNIT'
[Unit]
Description=Mealplanning portfolio stack (docker compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ubuntu/app/deploy/portfolio
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0
User=ubuntu
Group=docker

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable mealplanning.service   # 활성화만. .env 가 채워지기 전에는 start 하지 않는다

echo "user_data 완료 — SSH 로 들어와 deploy/portfolio/.env 를 채우고 시작할 것"
