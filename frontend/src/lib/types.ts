export type Citation = { document_id: string; chunk_id?: string | null; version?: number; quote: string };
export type Owner = "CANDIDATE" | "COLLEAGUE" | "JOINT";
export type SplitProposal = { assignments: Record<string, Owner>; adjustments_used: number; max_adjustments: number };
export type Message = {
  id: string; channel: "TEAM" | "ASSISTANT"; actor: string; content: string; citations: Citation[];
  meta: { kind?: string; event_id?: string; split_proposal?: SplitProposal; limited?: boolean };
  source_run_id: string | null; created_at: string;
};
export type Task = {
  id: string; title: string; status: string; owner: Owner; template_key: string | null;
  target_section: string | null; delegation_id: string | null; result: { summary?: string; citations?: Citation[] } | null; version: number;
};
export type Artifact = { id: string; sections: Record<string, string>; version: number };
export type Approval = {
  id: string; run_id: string; tool_name: string; args: Record<string, unknown>; status: string; expires_at: string;
  before_after: { before?: string; after?: string; section?: string; task_id?: string }; delegation_id: string | null;
};
export type Run = { id: string; kind: string; status: string; error_code: string | null; result: unknown };
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

export const ACTOR_LABEL: Record<string, string> = {
  CANDIDATE: "나", COLLEAGUE: "이도현", MANAGER: "한서윤 팀장", ASSISTANT: "AI 어시스턴트", SYSTEM: "알림",
};
export const OWNER_LABEL: Record<Owner, string> = { CANDIDATE: "나", COLLEAGUE: "이도현", JOINT: "공동" };
export const TASK_STATUS: Record<string, [string, string]> = {
  TODO: ["할 일", ""], IN_PROGRESS: ["진행 중", "info"], REVIEW: ["검토 대기", "warning"], DONE: ["완료", "success"], CANCELLED: ["취소", ""],
};

export function fmtClock(min: number): string {
  const m = Math.max(0, Math.floor(min));
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}
