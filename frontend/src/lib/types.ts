export type Citation = { document_id: string; chunk_id?: string; version?: number; quote: string; tool_call_id?: string };
export type Message = {
  id: string; channel: "TEAM" | "ASSISTANT"; actor: string; content: string; citations: Citation[];
  meta: { kind?: string; delegation_proposal?: DelegationProposal; event_id?: string; limited?: boolean };
  source_run_id: string | null; created_at: string;
};
export type DelegationProposal = {
  source_message_id: string; title: string; target_section: "evidence"; allowed_tools: string[];
  filters: Record<string, string>;
};
export type Task = {
  id: string; title: string; status: string; owner: "CANDIDATE" | "COLLEAGUE"; template_key: string | null;
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
  session: Session; artifact: Artifact | null; tasks: Task[]; messages: Message[]; active_run: Run | null;
  approvals: Approval[]; brief: { title: string; manager: string; colleague: string; public_brief: string; company_name: string; service_name: string };
  mode: string;
};

export const SECTIONS: { id: string; title: string; hint: string }[] = [
  { id: "problem", title: "문제와 대상", hint: "먼저 해결할 문제와 대상 사용자를 직접 정의하세요." },
  { id: "evidence", title: "수치·출처·한계", hint: "근거 수치와 출처, 데이터의 한계를 정리하세요. 동료에게 위임한 조사 결과는 승인 후 이 섹션에만 반영됩니다." },
  { id: "options", title: "비교한 대안과 선택 이유", hint: "검토한 대안과 우선순위, 선택 이유를 적으세요." },
  { id: "experiment", title: "가설·지표·실험 방법", hint: "가설, 성공/보호 지표, 실험 방법을 적으세요." },
  { id: "risks", title: "제약·불확실성·추가 확인", hint: "운영 제약, 불확실성, 추가로 확인할 점을 적으세요." },
];

export const ACTOR_LABEL: Record<string, string> = {
  CANDIDATE: "나", COLLEAGUE: "이도현 (AI 동료)", MANAGER: "한서윤 (팀장)", ASSISTANT: "어시스턴트", SYSTEM: "시스템",
};
export const TASK_STATUS: Record<string, [string, string]> = {
  TODO: ["할 일", ""], IN_PROGRESS: ["진행 중", "info"], REVIEW: ["검토 대기", "warning"], DONE: ["완료", "success"], CANCELLED: ["취소", ""],
};
