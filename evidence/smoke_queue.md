# 대기열(RabbitMQ) 스모크 (2026-10-20 15:27 KST)
```
PASS agent health에 대기열 활성 — {"enabled": true, "counts": {"dayzero.report": 0, "dayzero.report.retry": 0, "dayzero.report.dlq": 0}}
PASS 제출 → outbox job 발행(DONE) → RabbitMQ 처리 → 리포트 READY — report=READY, job={'status': 'DONE', 'attempt': 1}
PASS 실패 작업 재시도 3회 후 DLQ 이동 — x-attempt=3, 소요 6.1s(지연 재시도 2회 × 3s), last_error=RuntimeError: report build failed: NOT_FOUND
PASS 재시도 간 지연(≥6초) — 6.1s
PASS FAILED 리포트 관리자 재생성 → 큐 재처리 → READY — 202 READY
PASS 처리 큐·재시도 큐 잔여 0 — {"dayzero.report": 0, "dayzero.report.retry": 0, "dayzero.report.dlq": 0}
결과: 6/6 PASS
```
