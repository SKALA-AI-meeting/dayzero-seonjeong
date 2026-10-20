export type StreamEvent = {
  event_id: string;
  seq: number;
  session_id: string;
  run_id: string | null;
  occurred_at: string;
  type: string;
  payload: Record<string, unknown>;
};

const TYPES = [
  "RUN_STARTED", "TOOL_START", "TOOL_END", "COLLEAGUE_MESSAGE", "MANAGER_MESSAGE", "SYSTEM_NOTICE",
  "CANDIDATE_MESSAGE", "APPROVAL_REQUIRED", "APPROVAL_DECIDED", "TASK_UPDATED", "ARTIFACT_UPDATED", "SPLIT_UPDATED",
  // 턴 기반 이벤트 엔진: 이벤트 발생(가상 시각 갱신)·건너뜀
  "EVENT_FIRED", "EVENT_SKIPPED", "OBSERVATION_RECORDED",
  "DONE", "FAILED", "SESSION_DONE", "REPORT_READY", "REPORT_FAILED",
];

/** EventSource 래퍼: seq 기반 중복 제거, 끊기면 브라우저가 Last-Event-ID로 재접속. */
export function subscribe(
  sessionId: string,
  afterSeq: number,
  onEvent: (e: StreamEvent) => void,
  onStatus: (s: "open" | "reconnecting") => void,
): () => void {
  let last = afterSeq;
  const es = new EventSource(`/api/v1/sessions/${sessionId}/events?after_seq=${afterSeq}`);
  const handle = (msg: MessageEvent) => {
    const data = JSON.parse(msg.data) as StreamEvent;
    if (data.seq <= last) return;
    last = data.seq;
    onEvent(data);
  };
  TYPES.forEach((t) => es.addEventListener(t, handle as EventListener));
  es.onopen = () => onStatus("open");
  es.onerror = () => onStatus("reconnecting");
  return () => es.close();
}
