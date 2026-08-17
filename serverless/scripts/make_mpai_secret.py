"""`mp-ai/runtime` 시크릿을 만든다 — mp/prod 에서 «필요한 것만» 옮긴다.

왜 복사하나: 실행 역할의 permissions boundary 가 `secretsmanager:GetSecretValue` 를
`mp-ai/*` 로만 허용한다(`mp-ai-boundary.json` RuntimeOwnResources). 의도된 설계이고,
`iam.tf` 머리말에도 *"`mp/prod/*` 시크릿은 이 역할들이 못 읽는다 … 관리자 몫이 아니라
우리 몫"* 이라고 적어 뒀다.

🔴 값은 절대 출력하지 않는다. 길이와 키 이름만 찍는다 — 로그가 곧 유출 경로다
   (`serverless/common/secrets.py` 의 같은 규약).

🔴 복사본이라 **회전하면 갈라진다.** 그래서 필요한 5+2개만 옮기고, 어디서 왔는지를
   description 에 박아 둔다. 원본이 회전하면 이 스크립트를 다시 돌리면 된다(멱등).
"""
import json
import subprocess
import sys

REGION = "ap-northeast-2"
DEST = "mp-ai/runtime"

# (대상 필드, 원본 시크릿, 원본 필드) — 근거는 EKS 파드 실측(2026-08-18):
#   배치 5종  = pipeline CronJob   PGUSER=svc_pipeline · ES_USER=mp_pipeline_writer
#   chat-api  = mp-chat            PGUSER=svc_chat     · ES_USER=mp_recipe_reader
#   ocr-worker= mp-ocr             PGUSER=svc_ocr
MAP = [
    ("PGPASSWORD_PIPELINE",      "mp/prod/pg-roles",     "svc_pipeline"),
    ("PGPASSWORD_CHAT",          "mp/prod/pg-roles",     "svc_chat"),
    ("PGPASSWORD_OCR",           "mp/prod/pg-roles",     "svc_ocr"),
    ("ES_PASSWORD_PIPELINE",     "mp/prod/data-secrets", "ES_PIPELINE_WRITER_PASSWORD"),
    ("ES_PASSWORD_RECIPE_READER", "mp/prod/data-secrets", "ES_RECIPE_READER_PASSWORD"),
    ("GEMINI_API_KEY",           "mp/prod/app-secrets",  "GEMINI_API_KEY"),
    ("CHAT_GEMINI_API_KEY",      "mp/prod/app-secrets",  "CHAT_GEMINI_API_KEY"),
]


def get(name):
    out = subprocess.check_output(
        ["aws", "secretsmanager", "get-secret-value", "--region", REGION,
         "--secret-id", name, "--query", "SecretString", "--output", "text"],
        stderr=subprocess.PIPE, timeout=60).decode()
    return json.loads(out)


src_cache, bundle, missing = {}, {}, []
for dest_key, src_name, src_key in MAP:
    if src_name not in src_cache:
        src_cache[src_name] = get(src_name)
    v = src_cache[src_name].get(src_key)
    if not v:
        missing.append(f"{dest_key} (= {src_name}:{src_key})")
        continue
    bundle[dest_key] = v

print("── 옮길 필드")
for k in sorted(bundle):
    print("    %-28s %d자" % (k, len(bundle[k])))
if missing:
    print("── 🔴 원본이 비어 있어 못 옮긴 것")
    for m in missing:
        print("    ", m)

if not bundle:
    print("🔴 옮길 것이 없다 — 중단")
    sys.exit(1)

payload = json.dumps(bundle)
DESC = ("mp-ai Lambda runtime creds. Copied from mp/prod/{pg-roles,data-secrets,app-secrets} "
        "because the execution-role boundary only allows secretsmanager on mp-ai/*. "
        "Rotate the source first, then re-run scripts/make_mpai_secret.py.")

# 멱등 — 있으면 값만 갱신, 없으면 만든다.
try:
    subprocess.check_output(
        ["aws", "secretsmanager", "describe-secret", "--region", REGION, "--secret-id", DEST],
        stderr=subprocess.PIPE, timeout=60)
    exists = True
except subprocess.CalledProcessError:
    exists = False

if exists:
    subprocess.check_output(
        ["aws", "secretsmanager", "put-secret-value", "--region", REGION,
         "--secret-id", DEST, "--secret-string", payload], stderr=subprocess.PIPE, timeout=60)
    print(f"── 🔵 갱신 완료: {DEST} ({len(bundle)}개 필드)")
else:
    subprocess.check_output(
        ["aws", "secretsmanager", "create-secret", "--region", REGION,
         "--name", DEST, "--description", DESC, "--secret-string", payload],
        stderr=subprocess.PIPE, timeout=60)
    print(f"── 🔵 생성 완료: {DEST} ({len(bundle)}개 필드)")
