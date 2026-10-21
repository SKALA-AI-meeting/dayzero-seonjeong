export type Citation = { document_id: string; chunk_id?: string | null; version?: number; quote: string };
export type Owner = "UNASSIGNED" | "CANDIDATE" | "COLLEAGUE" | "SPLIT";
export type SplitProposal = { T1: "CANDIDATE" | "COLLEAGUE"; T3: "CANDIDATE" | "COLLEAGUE"; faq_candidate: number };
export type Message = {
  id: string; channel: "TEAM"; actor: string; content: string; citations: Citation[]; turn: number;
  meta: { kind?: string; event_id?: string; label?: string; to?: string; split_proposal?: SplitProposal; elapsed_seconds?: number };
  source_run_id: string | null; created_at: string;
};
export type Task = { id: string; key: string; title: string; status: string; owner: Owner; eta: string | null; note: string | null; version: number };
export type Artifact = { id: string; key: string; title: string; body: string; version: number };
export type Approval = {
  id: string; run_id: string; tool_name: string; args: Record<string, unknown>; status: string; expires_at: string;
  before_after: { artifact_key?: string; title?: string; before?: string; after?: string; targets?: string[]; task_key?: string };
};
export type Run = { id: string; kind: string; status: string; error_code: string | null; result: unknown };
export type Session = { id: string; status: string; phase: string; version: number; turn_count: number; elapsed_seconds: number; last_stream_seq: number };
export type Snapshot = {
  session: Session; artifacts: Artifact[]; tasks: Task[]; messages: Message[]; active_run: Run | null;
  approvals: Approval[]; mode: string; events: string[];
  brief: { title: string; company: string; task_summary: string; 
    characters: Record<string, { name: string; role: string }> };
  clock: { elapsed_seconds: number; remaining_seconds: number; server_now: string };
  colleague: { offline: boolean };
  split: { proposal: SplitProposal; rounds: number; confirmed: boolean; max_rounds: number } | null;
};

/** 내 산출물(T1~T5). T4·T5는 이벤트(E4·E2)에서 생긴다. 설계서 3장 태스크 보드. */
export const ARTIFACT_HINT: Record<string, string> = {
  T1: "앱 공지용 이벤트 안내문을 300자 내외로 작성하세요.",
  T2: "고객 FAQ 5개. 서윤 님이 작성한 2개(Q1·Q2)에서 시작합니다.",
  T3: "리워드·일정 표. 서윤 님 초안에서 시작합니다.",
  T5: "앱 푸시 문구 2개(각 40자 이내).",
  T4: "팀장님께 보낼 현재 상태 3줄 요약.",
};
export const DOC_TITLE: Record<string, string> = {
  brief: "이벤트 기획 브리프", "reward-table": "리워드·일정 표 (서윤 초안)", "faq-draft": "FAQ 초안 2개 (서윤)", "tone-guide": "고객 공지 톤 가이드",
};

/** 화면 문구 단일 매핑 (DESIGN_GUIDE). 인물: 한서윤 = AI 동료, 박준호 = 팀장 (docs/SCENARIO_SC_A.md 3장). */
export const ACTOR: Record<string, { name: string; initial: string; badge?: [string, string]; avatar: string }> = {
  MANAGER: { name: "박준호", initial: "박", badge: ["팀장", ""], avatar: "" },
  COLLEAGUE: { name: "한서윤", initial: "한", badge: ["AI 동료", "info"], avatar: "colleague" },
  CANDIDATE: { name: "나", initial: "나", avatar: "me" },
  SYSTEM: { name: "알림", initial: "!", avatar: "" },
};
export const OWNER_LABEL: Record<Owner, string> = { UNASSIGNED: "미정", CANDIDATE: "나", COLLEAGUE: "한서윤", SPLIT: "나눠서" };
export const TASK_STATUS: Record<string, [string, string]> = {
  TODO: ["할 일", ""], IN_PROGRESS: ["진행 중", "info"], DONE: ["완료", "success"],
};
export const COPY = {
  brief_title: "핏모아 운영팀에 오신 것을 환영합니다",
  composer: "메시지를 입력하세요",
  saving: "저장 중…", saved: "저장됨", save_failed: "저장하지 못했습니다. 작성한 내용은 그대로 남아 있습니다.",
  reconnecting: "연결을 복구하고 있습니다. 저장된 작업은 유지됩니다.",
  approval_title: "서윤 님의 수정안을 확인해 주세요",
  approval_stale: "그 사이 산출물이 바뀌어 이 수정안을 적용하지 않았습니다. 현재 내용은 유지했습니다.",
  submit_confirm: "업무를 종료하면 산출물과 대화를 더 수정할 수 없습니다.",
  ai_failed: "답장을 받지 못했습니다. 작성 중인 산출물은 저장되어 있습니다.",
  report_failed: "리포트를 생성하지 못했습니다. 지원자의 기록은 안전하게 저장되어 있습니다.",
  report_limit: "이 리포트는 단일 가상 과제에서 관찰된 행동 코드와 근거 원문만 정리합니다. 점수·등급·합불은 없으며 최종 판단은 사람이 합니다.",
};
export const ERROR_COPY: Record<string, string> = {
  RUN_BUSY: "답장을 기다리는 중입니다. 답장이나 승인 결정 뒤에 다시 보내 주세요.",
  APPROVAL_STALE: COPY.approval_stale, APPROVAL_EXPIRED: "승인 요청이 만료되었습니다. 필요하면 서윤 님에게 다시 요청해 주세요.",
  VERSION_CONFLICT: "다른 변경이 먼저 저장되었습니다. 내 입력은 보존되어 있습니다.",
  SESSION_SUBMITTED: "종료된 세션은 수정할 수 없습니다.",
  UNAUTHENTICATED: "접속 정보가 만료되었습니다. 초대 링크로 다시 입장해 주세요.",
  LLM_UNAVAILABLE: COPY.ai_failed, AGENT_ERROR: COPY.ai_failed,
};
export function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" });
}

export function fmtElapsed(seconds: number) { const s = Math.max(0, Math.floor(seconds)); return `${String(Math.floor(s/60)).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`; }
