# 팀원 SSH 공개키 드롭인

이 디렉토리에 팀원의 **공개키**(`.pub`)를 `<이름>.pub`으로 넣으면, 다음 실행 시 전 VM(`ubuntu`)의 `authorized_keys`에 등록됩니다.

```bash
# 예: 팀원 키 추가
cp ~/받은키/alice.pub roles/team_ssh_keys/files/alice.pub
cd infra/ansible
ansible-playbook site.yml --tags team_keys      # 전 VM에 배포 (additive)
```

- **공개키만** 넣으세요 (`.pub`). 개인키(`id_*` 확장자 없는 것)는 절대 금지.
- `authorized_key`는 `exclusive: false`라 **기존 키를 지우지 않습니다**(잠금 사고 방지).
- 제거하려면 파일 삭제만으론 안 되고(additive), 대상 VM에서 해당 키를 직접 제거해야 합니다.
