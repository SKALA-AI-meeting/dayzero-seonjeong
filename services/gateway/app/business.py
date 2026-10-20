"""Business tool logic owned by the gateway (business-mcp forwards here). DAYZERO_EXAM_SCENARIO §5."""
from __future__ import annotations

import json

from shared.config import DATASET_VERSION, SCENARIO_ID
from shared.db import all_

DIMENSIONS = {"overall", "group_size"}
GROUP_SIZES = {"small", "medium", "large"}
GROUP_LABEL = {"small": "소규모(5명 이하)", "medium": "중규모(6~10명)", "large": "대규모(11명 이상)", "all": "전체"}
INTERVIEW_TAGS = {"awkward", "missed_schedule", "pace", "positive", "host", "time", "location"}


class ToolError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code, self.message, self.retryable = code, message, retryable


def rate(num: int, den: int) -> float | None:
    return None if den == 0 else round(num / den, 6)


def rejoin_metrics(c, args: dict) -> dict:
    dimension = args.get("dimension")
    group_size = (args.get("filters") or {}).get("group_size")
    if dimension not in DIMENSIONS:
        raise ToolError("INVALID_ARGUMENT", "dimension은 overall|group_size만 허용됩니다")
    if group_size is not None and group_size not in GROUP_SIZES:
        raise ToolError("INVALID_ARGUMENT", "group_size 필터는 small|medium|large만 허용됩니다")
    group = "'all'" if dimension == "overall" else "group_size"
    rows = all_(c, f"""SELECT {group} AS segment, SUM(first_time_participants)::int AS first_time_participants,
                              SUM(rejoined_within_30d)::int AS rejoined_within_30d
                       FROM rejoin_facts WHERE scenario_id=%s AND dataset_version=%s
                         AND (%s::text IS NULL OR group_size=%s) GROUP BY 1 ORDER BY 1""",
                   (SCENARIO_ID, DATASET_VERSION, group_size, group_size))
    out = [{**r, "label": GROUP_LABEL.get(r["segment"], r["segment"]),
            "rejoin_rate": rate(r["rejoined_within_30d"], r["first_time_participants"])}
           for r in rows if r["first_time_participants"] is not None]
    return {"rows": out, "unit": "명(최근 분기 첫 모임 참가자); rate 0~1", "monthly_active_users": 30000,
            "source_version": DATASET_VERSION, "dimension": dimension, "filters": {"group_size": group_size} if group_size else {}}


def interview_notes(c, args: dict, *, released: bool) -> dict:
    if not released:
        raise ToolError("NOT_FOUND", "사용자 인터뷰 요약 자료는 아직 공유되지 않았습니다")
    tags = args.get("tags") or []
    limit = args.get("limit", 8)
    if not isinstance(tags, list) or len(tags) > 3 or any(t not in INTERVIEW_TAGS for t in tags):
        raise ToolError("INVALID_ARGUMENT", f"tags는 최대 3개이며 다음 값만 허용됩니다: {sorted(INTERVIEW_TAGS)}")
    if not isinstance(limit, int) or not 1 <= limit <= 8:
        raise ToolError("INVALID_ARGUMENT", "limit은 1~8입니다")
    rows = all_(c, """SELECT id, group_size, tags, quote FROM interview_notes
                      WHERE scenario_id=%s AND (%s::jsonb = '[]'::jsonb OR tags ?| %s::text[])
                      ORDER BY id LIMIT %s""", (SCENARIO_ID, json.dumps(tags), tags, limit))
    return {"items": rows,
            "sampling_note": "첫 모임 참가자 8명 인터뷰입니다. 표본 조사가 아니므로 전체 사용자의 의견 비중을 대표하지 않습니다."}
