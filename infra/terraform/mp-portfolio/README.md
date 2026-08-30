# mp-portfolio — 포트폴리오 호스트 (Lightsail)

프로젝트 종료 후 서비스를 보여주기 위한 단일 호스트 스택. `aws-platform` 과 **완전히 별개**이고,
그쪽이 destroy 된 뒤에도 남는다.

## 구축

```bash
cp backend.conf.example backend.conf     # 필요시 프로필 수정
terraform init -backend-config=backend.conf
terraform plan  -var profile=mp-platform -out tfplan    # 🔴 to destroy 가 0 인지 눈으로 확인
terraform apply tfplan
```

apply 후 액세스 키를 손으로 만든다 (terraform 은 비밀을 만들지 않는다 — tfstate 평문).

```bash
aws iam create-access-key --user-name mp-portfolio-backup --profile mp-platform
```

## 호스트 준비 이후

`user_data.sh` 가 Docker·스왑·`vm.max_map_count`·레포 클론·systemd 유닛까지 끝내 둔다.
SSH 로 들어가서:

```bash
cd ~/app/deploy/portfolio
cp .env.example .env && chmod 600 .env && vi .env   # 시크릿 채우기
docker compose build          # 최초 1회, 약 30~40분 (x86 빌드)
docker compose up -d
./bootstrap.sh                # PG 복원 + ES 색인
```

## 요금

| 항목 | 월 |
|---|---|
| Lightsail medium_3_0 (2 vCPU / 4 GiB / 80 GiB / 4 TB) | $24.00 |
| S3 (시드·백업) | ~$0.25 |

스토리지·고정 IP·전송량이 요금에 포함이라 별도 청구가 없다.
