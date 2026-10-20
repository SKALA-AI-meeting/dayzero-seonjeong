export type Citation = { document_id: string; chunk_id?: string | null; version?: number; quote: string };
export type Owner = "CANDIDATE" | "COLLEAGUE" | "JOINT";
export type SplitProposal = { assignments: Record<string, Owner>; adjustments_used: number; max_adjustments: number };
export type Message = {
  id: string; channel: "TEAM"; actor: string; content: string; citations: Citation[];
  meta: { kind?: string; event_id?: string; split_proposal?: SplitProposal; limited?: boolean };
  source_run_id: string | null; created_at: string;
};
export type Task = {
  id: string; title: string; status: string; owner: Owner; template_key: string | null;
  target_section: string | null; delegation_id: string | null; result: { summary?: string; citations?: Citation[]; rejected?: boolean } | null; version: number;
};
export type Artifact = { id: string; sections: Record<string, string>; version: number };
export type Approval = {
  id: string; run_id: string; tool_name: string; args: Record<string, unknown>; status: string; expires_at: string;
  before_after: { before?: string; after?: string; section?: string; task_id?: string }; delegation_id: string | null;
};
export type Run = { id: string; kind: string; status: string; error_code: string | null; result: unknown; task_id?: string | null };
export type Session = { id: string; status: string; phase: string; version: number; last_stream_seq: number };
export type Snapshot = {
  session: Session; artifact: Artifact | null; tasks: Task[]; messages: Message[]; active_run: Run | null; active_runs: Run[];
  approvals: Approval[]; mode: string;
  brief: { title: string; manager: string; colleague: string; public_brief: string; company_name: string; service_name: string; duration_minutes: number };
  clock: { elapsed_min: number; duration_min: number; remaining_min: number };
  split: { assignments: Record<string, Owner>; adjustments_used: number; confirmed: boolean } | null;
};

/** 최종 제출물 5개 항목(DAYZERO_EXAM_SCENARIO §4). 작성 순서·분담은 지원자가 조정 가능. */
export const SECTIONS: { id: string; title: string; hint: string }[] = [
  { id: "problem", title: "1. 문제 정의와 대상 사용자", hint: "어떤 사용자의 어떤 문제를 풀지 정의하세요." },
  { id: "interview_evidence", title: "2. 사용자 인터뷰에서 찾은 근거", hint: "사용자 인터뷰 요약에서 찾은 근거를 정리하세요." },
  { id: "features", title: "3. 핵심 기능 제안", hint: "재참여를 유도할 핵심 기능을 제안하세요." },
  { id: "similar_cases", title: "4. 비슷한 서비스 사례", hint: "참고할 만한 비슷한 서비스 사례와 비교 기준을 적으세요." },
  { id: "metrics_timeline", title: "5. 성공 지표와 출시 일정", hint: "성공 지표와 출시 일정을 적으세요." },
];

/** 화면 문구 단일 매핑 (DESIGN_GUIDE §10.2, §11). 내용 예시는 DAYZERO_EXAM_SCENARIO 기준. */
export const ACTOR: Record<string, { name: string; initial: string; badge?: [string, string]; avatar: string }> = {
  MANAGER: { name: "한서윤", initial: "한", badge: ["팀장", ""], avatar: "" },
  COLLEAGUE: { name: "이도현", initial: "이", badge: ["AI 동료", "info"], avatar: "colleague" },
  CANDIDATE: { name: "나", initial: "나", avatar: "me" },
  SYSTEM: { name: "알림", initial: "!", avatar: "" },
};
export const OWNER_LABEL: Record<Owner, string> = { CANDIDATE: "나", COLLEAGUE: "이도현 · AI 동료", JOINT: "공동" };
export const OWNER_SHORT: Record<Owner, string> = { CANDIDATE: "나", COLLEAGUE: "이도현", JOINT: "공동" };
export const TASK_STATUS: Record<string, [string, string]> = {
  TODO: ["할 일", ""], IN_PROGRESS: ["진행 중", "info"], REVIEW: ["검토 필요", "warning"], DONE: ["완료", "success"], CANCELLED: ["취소됨", ""],
};
export const CHANNELS = {
  notice: { id: "notice", name: "프로젝트-공지", desc: "팀장 공지와 시스템 알림입니다. 이 채널에는 입력할 수 없습니다." },
  team: { id: "team", name: "재참여-개선", desc: "이도현 동료와 업무를 나누고 자료를 함께 확인하세요. 팀장 공지는 # 프로젝트-공지에 올라옵니다." },
} as const;
export const COPY = {
  brief_title: "루프랩 프로덕트팀에 합류했습니다",
  composer: "이도현 동료에게 조사나 업무를 요청하세요",
  saving: "저장 중…", saved: "저장됨", save_failed: "저장하지 못했습니다. 작성한 내용은 이 브라우저에 남아 있습니다.",
  reconnecting: "연결을 복구하고 있습니다. 저장된 작업은 유지됩니다.",
  investigating: "자료를 확인하고 있어요.", approval_title: "문서 변경 승인이 필요합니다",
  approval_stale: "문서가 그 사이 변경되어 이 제안을 적용할 수 없습니다. 현재 내용은 유지했습니다.",
  empty_sections: "비어 있는 섹션이 있습니다. 불완전한 상태로도 제출할 수 있습니다.",
  submit_confirm: "제출 후에는 문서와 진행 중 작업을 수정할 수 없습니다.", submitted: "기획안이 제출되었습니다",
  ai_failed: "조사를 완료하지 못했습니다. 작성 중인 기획안은 저장되어 있습니다.",
  report_failed: "리포트를 생성하지 못했습니다. 지원자 제출물은 안전하게 저장되어 있습니다.",
  report_limit: "이 리포트는 단일 가상 과제에서 관찰된 행동을 정리하며 성격·채용 성과를 단정하지 않습니다.",
};
export const ERROR_COPY: Record<string, string> = {
  RUN_BUSY: "이도현 동료가 이전 요청에 답하는 중입니다. 답변이 끝난 뒤 다시 보내 주세요.",
  APPROVAL_STALE: COPY.approval_stale, APPROVAL_EXPIRED: "승인 요청이 만료되었습니다. 필요하면 태스크에서 수정 요청해 주세요.",
  VERSION_CONFLICT: "다른 변경이 먼저 저장되었습니다. 내 입력은 보존되어 있습니다.",
  SESSION_SUBMITTED: "제출된 세션은 수정할 수 없습니다.", LIMIT_REACHED: "분담 조정은 최대 3회까지 가능합니다. 현재 안으로 확정해 주세요.",
  UNAUTHENTICATED: "접속 정보가 만료되었습니다. 초대 링크로 다시 입장해 주세요.",
  LLM_UNAVAILABLE: COPY.ai_failed, AGENT_ERROR: COPY.ai_failed,
};
export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" });
}

export function fmtClock(min: number): string {
  const m = Math.max(0, Math.floor(min));
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
