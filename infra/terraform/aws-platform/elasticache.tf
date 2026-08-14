# ElastiCache for Valkey — 앱 캐시 (C-14 · A1)
#
# 온프렘 Redis(OT-Container-Kit + Sentinel 5파드)를 대체한다. 🔴 판단축은 비용이 아니라
# **Sentinel 운영 부담**이었다 — 오퍼레이터 결함 우회 코드가 지금도 프로덕션에 남아 있다
# (`chat/app/db.py` · `price/app/db.py`). 상세 근거 = 체크리스트 C-14 근거절.
#
# 🔴 **`mp-redis-pgsync` 는 이 리소스가 대체하지 않는다** — 383 ops/s 로 앱 Redis 의 64배라
#    관리형에 얹으면 비용·AZ 홉만 는다. 정본이 명시적으로 대상에서 뺐고 인클러스터로 남는다.
#
# 🟢 **앱 코드 변경 0줄** — 비-Sentinel 폴백이 이미 기본 분기다(`if settings.redis_sentinels: … else`).
#    config 에서 `REDIS_SENTINELS` 를 비우고 `REDISHOST` 를 아래 엔드포인트로 바꾸면 된다.
#    🔴 `envFrom.configMapRef` 는 파드 기동 시점 주입이라 **`rollout restart` 가 별도로 필요**하다.

# ── 서브넷 그룹 — 데이터 티어 (밖으로 나가는 경로 없음) ───────────────────────
# 🔴 `node` 가 아니라 `data` 서브넷을 쓴다. ElastiCache 는 아웃바운드를 시작하지 않으므로
#    NAT 가 없는 서브넷이 맞고, 그게 이 티어가 존재하는 이유다(vpc_service.tf ③).
resource "aws_elasticache_subnet_group" "valkey" {
  name        = "mp-cache-subnets"
  description = "Data tier subnets (no egress) for ElastiCache"
  subnet_ids  = [for s in aws_subnet.data : s.id]

  tags = { Name = "mp-cache-subnets" }
}

# ── 보안그룹 ─────────────────────────────────────────────────────────────────
# 🔴 **이 SG 가 유일한 보호막이다.** 정본이 encryption-in-transit·AUTH 를 **끈 채로 가기로**
#    했으므로(켜려면 8파일 50~70줄 · 지원 코드 0건), VPC 안에서 평문으로 흐른다.
#    ⇒ 온프렘에서 netpol 이 하던 역할을 여기서는 SG 가 대신한다. 넓히지 말 것.
# 🔴 description 은 **ASCII 만** — security_groups.tf 머리말의 결함 기록 참조
#    (`plan` 은 통과하고 `apply` 에서만 터진다).
resource "aws_security_group" "elasticache" {
  name        = "mp-sg-elasticache"
  description = "ElastiCache Valkey. Clients = EKS nodes/pods only."
  vpc_id      = aws_vpc.service.id

  tags = { Name = "mp-sg-elasticache" }

  lifecycle {
    create_before_destroy = true
  }
}

# 클라이언트 = EKS 노드 SG. 🔴 Cilium ENI 라 **파드도 이 SG 를 물려받는다**(A-44) —
#    즉 이 한 줄이 "앱 파드 전체"를 뜻한다. 파드 단위 통제는 Cilium netpol 의 몫이다.
resource "aws_vpc_security_group_ingress_rule" "elasticache_from_nodes" {
  security_group_id            = aws_security_group.elasticache.id
  referenced_security_group_id = aws_security_group.node.id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  description                  = "Valkey from EKS nodes and pods"
}

# 🔴 노드 간 복제용 self 규칙 2개 — 없으면 **replica 가 primary 를 따라가지 못한다.**
#    Multi-AZ 2노드는 replica 가 primary 로 6379 를 여는 구조이고, 두 노드가 같은 SG 를
#    쓰므로 ingress(self) + egress(self) 가 둘 다 있어야 한다.
#    ⚠️ 이 SG 에는 egress 를 전면 허용하지 않는다 — Terraform 이 만든 SG 는 기본 egress 가
#      비어 있고, ElastiCache 는 아웃바운드를 시작할 일이 복제 말고는 없다.
resource "aws_vpc_security_group_ingress_rule" "elasticache_self" {
  security_group_id            = aws_security_group.elasticache.id
  referenced_security_group_id = aws_security_group.elasticache.id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  description                  = "Replication between cache nodes"
}

resource "aws_vpc_security_group_egress_rule" "elasticache_self" {
  security_group_id            = aws_security_group.elasticache.id
  referenced_security_group_id = aws_security_group.elasticache.id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  description                  = "Replication between cache nodes"
}

# ── 복제 그룹 ────────────────────────────────────────────────────────────────
resource "aws_elasticache_replication_group" "valkey" {
  replication_group_id = "mp-cache"
  description          = "App cache (Valkey). Replaces onprem Redis + Sentinel."

  engine         = "valkey"
  engine_version = var.cache_engine_version
  node_type      = var.cache_node_type
  port           = 6379

  # 🔴 **2노드인 이유는 가용성이 아니라 잡 상태다.** 내용물은 전부 재생성 가능한 캐시지만
  #    예외가 `video:lock:{}` 이다 — 잃으면 **중복 Gemini 호출 = 중복 과금**이라 월 $11 차액을
  #    상쇄할 수 있다. 진행 중 OCR·video 잡 상태도 함께 날아가 유저가 폴링하다 404 를 본다.
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  multi_az_enabled           = true

  subnet_group_name  = aws_elasticache_subnet_group.valkey.name
  security_group_ids = [aws_security_group.elasticache.id]

  # 🔴 **전송 암호화·AUTH 는 끈다 — 정본이 명시적으로 감수한 부채다**(C-14 "포기하는 것").
  #    켜면 클라이언트 8파일 50~70줄이 필요한데 지원 코드가 0건이다. 보호는 위 SG 가 맡는다.
  #    ⇒ 0-15(ES PoLP)와 같은 성격의 부채가 하나 남는다. 켜는 건 별건으로 다룬다.
  transit_encryption_enabled = false
  # 🟢 저장 암호화는 **켠다** — 정본이 포기한 것은 *전송* 암호화와 AUTH 뿐이고,
  #    저장 암호화는 클라이언트에 아무 영향이 없으며 추가 비용도 없다(AWS 관리형 키).
  at_rest_encryption_enabled = true

  # 🔴 스냅샷을 받지 않는다 — 내용물이 **재생성 가능한 캐시**다(C-14 실측: 키가 전부
  #    Gemini 추출 캐시·딜 캐시·단기 잡상태). 백업은 복구가치가 없고 비용만 는다.
  snapshot_retention_limit = 0

  auto_minor_version_upgrade = true
  apply_immediately          = false

  tags = { Name = "mp-cache" }
}
