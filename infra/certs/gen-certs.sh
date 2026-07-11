#!/usr/bin/env bash
# 로컬 CA + 서버 인증서(IP SAN) 생성. 멱등(이미 있으면 skip).
# CA 키(ca.key)와 서버 키/인증서는 gitignore. ca.crt(트러스트 앵커)만 배포.
set -e
cd "$(dirname "$0")"
DAYS_CA=3650
DAYS_CERT=825   # 브라우저 호환 위해 <825일

# 1) Root CA (최초 1회)
if [ ! -f ca.key ]; then
  openssl genrsa -out ca.key 4096
  openssl req -x509 -new -nodes -key ca.key -sha256 -days "$DAYS_CA" \
    -out ca.crt -subj "/C=KR/O=food-budget/CN=food-budget Local CA"
  echo "CA 생성"
fi

gen_cert() {  # 이름, IP
  local name=$1 ip=$2
  if [ -f "$name.crt" ]; then echo "$name.crt 존재 — skip"; return; fi
  openssl genrsa -out "$name.key" 4096
  openssl req -new -key "$name.key" -out "$name.csr" -subj "/C=KR/O=food-budget/CN=$ip"
  printf 'subjectAltName=IP:%s\nextendedKeyUsage=serverAuth\n' "$ip" > "$name.ext"
  openssl x509 -req -in "$name.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out "$name.crt" -days "$DAYS_CERT" -sha256 -extfile "$name.ext"
  rm -f "$name.csr" "$name.ext"
  echo "$name 인증서 생성 (SAN IP:$ip)"
}

gen_cert harbor  192.168.0.10
gen_cert grafana 192.168.0.11
echo "완료 — ca.crt(배포용), *.key(비밀)"
