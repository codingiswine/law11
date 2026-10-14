#!/bin/bash
# Claude Code PreToolUse 훅: 에이전트가 git commit을 실행하기 전에 백엔드 pytest를 돌린다.
# 실패하면 exit 2로 커밋을 막고, 실패 내용을 에이전트에게 돌려준다.
# ※ 직접 터미널에서 하는 커밋은 막지 않음 — 그 경우는 CI(.github/workflows/ci.yml)가 잡는다.

cmd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')

case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

cd "$CLAUDE_PROJECT_DIR/law11_backend" || exit 0

if ! out=$("$CLAUDE_PROJECT_DIR/.venv/bin/python" -m pytest tests/ -q 2>&1); then
  echo "pytest 실패로 커밋을 막았습니다. 테스트를 먼저 고치세요:" >&2
  echo "$out" | tail -30 >&2
  exit 2
fi
exit 0
