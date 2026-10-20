#!/usr/bin/env bash
# 메시지 큐(이전 대기열 가산점 구현) 잔재가 없는지 확인한다. 0건이어야 통과.
# 대상: git이 관리하는 파일 + .gitignore 밖의 새 파일(모델 캐시·node_modules·.venv 제외).
# 패턴을 조각으로 이어 붙여 이 스크립트·문서 자신이 검색에 걸리지 않게 한다. lock 파일은 해시 문자열 우연 일치라 제외.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
P="rab""bit|am""qp|pi""ka|dl""q|m""q\\."
HITS=$(git grep --untracked -niE "$P" -- . ':!*package-lock.json' ':!*uv.lock' || true)
if [ -n "$HITS" ]; then echo "$HITS"; echo "✗ $(echo "$HITS" | wc -l | tr -d ' ')건"; exit 1; fi
echo "✓ 0건"
