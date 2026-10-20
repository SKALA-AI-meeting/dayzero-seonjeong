"""Business tool logic owned by the gateway (business-mcp forwards here). SCENARIO_DATA §3."""
from __future__ import annotations

from shared.config import DATASET_VERSION, SCENARIO_ID
from shared.db import all_

ENUMS = {"device": {"mobile", "desktop"}, "visitor": {"new", "returning"}, "cart_value": {"low", "high"}}
DIMENSIONS = {"overall", "device", "visitor", "cart_value"}
PERIODS = {"baseline", "current"}
SUPPORT_TAGS = {"shipping", "transparency", "signup", "friction", "performance", "checkout", "coupon",
                "comparison", "deferred"}


class ToolError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code, self.message, self.retryable = code, message, retryable


def rate(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 6)


def funnel_metrics(c, args: dict) -> dict:
    period, dimension, filters = args.get("period"), args.get("dimension"), args.get("filters") or {}
    if period not in PERIODS:
        raise ToolError("INVALID_ARGUMENT", "period는 baseline|current만 허용됩니다")
    if dimension not in DIMENSIONS:
        raise ToolError("INVALID_ARGUMENT", "dimension은 overall|device|visitor|cart_value만 허용됩니다")
    if not isinstance(filters, dict):
        raise ToolError("INVALID_ARGUMENT", "filters는 객체여야 합니다")
    for k, v in filters.items():
        if k not in ENUMS or v not in ENUMS[k]:
            raise ToolError("INVALID_ARGUMENT", f"허용되지 않는 필터: {k}={v}")
    where = ["scenario_id=%s", "dataset_version=%s", "period=%s"]
    params: list = [SCENARIO_ID, DATASET_VERSION, period]
    for k, v in filters.items():  # column names come from the fixed ENUMS whitelist
        where.append(f"{k}=%s")
        params.append(v)
    group = "'all'" if dimension == "overall" else dimension
    rows = all_(c, f"""SELECT {group} AS segment, SUM(cart_sessions)::int AS cart_sessions,
                              SUM(checkout_sessions)::int AS checkout_sessions, SUM(orders)::int AS orders
                       FROM funnel_facts WHERE {' AND '.join(where)} GROUP BY 1 ORDER BY 1""", params)
    out = []
    for r in rows:
        if r["cart_sessions"] is None:
            continue
        out.append({**r,
                    "abandonment_rate": rate(r["cart_sessions"] - r["orders"], r["cart_sessions"]),
                    "checkout_abandonment_rate": rate(r["checkout_sessions"] - r["orders"], r["checkout_sessions"])})
    return {"rows": out, "unit": "sessions; rate 0~1", "source_version": DATASET_VERSION,
            "period": period, "dimension": dimension, "filters": filters}


def support_cases(c, args: dict) -> dict:
    tags = args.get("tags") or []
    limit = args.get("limit", 5)
    if not isinstance(tags, list) or len(tags) > 3 or any(t not in SUPPORT_TAGS for t in tags):
        raise ToolError("INVALID_ARGUMENT", f"tags는 최대 3개이며 다음 값만 허용됩니다: {sorted(SUPPORT_TAGS)}")
    if not isinstance(limit, int) or not 1 <= limit <= 5:
        raise ToolError("INVALID_ARGUMENT", "limit은 1~5입니다")
    rows = all_(c, """SELECT id, device, visitor, tags, quote FROM support_cases
                      WHERE scenario_id=%s AND (%s::jsonb = '[]'::jsonb OR tags ?| %s::text[])
                      ORDER BY id LIMIT %s""", (SCENARIO_ID, __import__("json").dumps(tags), tags, limit))
    return {"items": rows,
            "sampling_note": "과제용으로 선택한 합성 문의 사례입니다. 확률표본이 아니므로 전체 이탈 원인 비중을 추정할 수 없습니다."}
