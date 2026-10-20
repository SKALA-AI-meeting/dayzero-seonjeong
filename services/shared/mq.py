"""RabbitMQ 작업 큐(가산점: 대기열). 리포트 생성 작업을 큐에 넣어 처리하고 실패 시 재시도, 최종 실패는 DLQ.

토폴로지 (모두 durable, idempotent 선언)
  exchange  dayzero (direct)
  queue     dayzero.report        ← routing 'report'      (처리 큐)
  queue     dayzero.report.retry  ← routing 'report.retry' (TTL 3초 후 dead-letter → 'report' 로 복귀 = 지연 재시도)
  queue     dayzero.report.dlq    ← routing 'report.dlq'   (최대 시도 초과 메시지 보관)
DB jobs 테이블은 트랜잭션 아웃박스로 쓰고(제출과 같은 트랜잭션에 기록), agent 릴레이가 RabbitMQ로 발행한다.
"""
from __future__ import annotations

import json
import os
from typing import Callable

import pika

EXCHANGE = "dayzero"
Q_REPORT, Q_RETRY, Q_DLQ = "dayzero.report", "dayzero.report.retry", "dayzero.report.dlq"
MAX_ATTEMPTS = 3
RETRY_DELAY_MS = 3000


def url() -> str:
    return os.environ.get("RABBITMQ_URL", "")


def enabled() -> bool:
    return bool(url())


def connect() -> pika.BlockingConnection:
    params = pika.URLParameters(url())
    params.heartbeat = 30
    return pika.BlockingConnection(params)


def declare(ch) -> None:
    ch.exchange_declare(EXCHANGE, exchange_type="direct", durable=True)
    ch.queue_declare(Q_REPORT, durable=True)
    ch.queue_declare(Q_RETRY, durable=True, arguments={"x-message-ttl": RETRY_DELAY_MS,
                                                       "x-dead-letter-exchange": EXCHANGE, "x-dead-letter-routing-key": "report"})
    ch.queue_declare(Q_DLQ, durable=True)
    ch.queue_bind(Q_REPORT, EXCHANGE, "report")
    ch.queue_bind(Q_RETRY, EXCHANGE, "report.retry")
    ch.queue_bind(Q_DLQ, EXCHANGE, "report.dlq")


def publish(ch, routing: str, body: dict, attempt: int = 1, error: str | None = None) -> None:
    headers = {"x-attempt": attempt}
    if error:
        headers["x-last-error"] = error[:300]
    ch.basic_publish(EXCHANGE, routing, json.dumps(body).encode(),
                     pika.BasicProperties(delivery_mode=2, content_type="application/json", headers=headers))


def publish_report(body: dict) -> None:
    conn = connect()
    try:
        ch = conn.channel()
        declare(ch)
        ch.confirm_delivery()
        publish(ch, "report", body)
    finally:
        conn.close()


def consume_reports(handle: Callable[[dict], None], on_dead: Callable[[dict, str], None], stop) -> None:
    """처리 실패 시 x-attempt를 올려 retry 큐(지연 재시도)로, MAX_ATTEMPTS 초과 시 DLQ로 보내고 on_dead 호출."""
    conn = connect()
    ch = conn.channel()
    declare(ch)
    ch.basic_qos(prefetch_count=1)

    def on_msg(chx, method, props, raw):
        body = json.loads(raw)
        attempt = int((props.headers or {}).get("x-attempt", 1))
        try:
            handle(body)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            if attempt < MAX_ATTEMPTS:
                publish(chx, "report.retry", body, attempt + 1, err)
            else:
                publish(chx, "report.dlq", body, attempt, err)
                try:
                    on_dead(body, err)
                except Exception:  # noqa: BLE001
                    pass
        chx.basic_ack(method.delivery_tag)

    ch.basic_consume(Q_REPORT, on_msg)
    while not stop.is_set():
        conn.process_data_events(time_limit=1)
    conn.close()


def queue_counts() -> dict:
    conn = connect()
    try:
        ch = conn.channel()
        declare(ch)
        return {q: ch.queue_declare(q, passive=True).method.message_count for q in (Q_REPORT, Q_RETRY, Q_DLQ)}
    finally:
        conn.close()
