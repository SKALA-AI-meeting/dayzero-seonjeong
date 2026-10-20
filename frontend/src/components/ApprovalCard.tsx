"use client";
import { SECTIONS, type Approval } from "@/lib/types";

const TOOL_LABEL: Record<string, string> = {
  patch_artifact_section: "기획안 섹션 변경",
  update_task_status: "태스크 상태 변경",
};

export function ApprovalCard({ a, busy, onDecide }: { a: Approval; busy: boolean; onDecide: (d: "APPROVE" | "REJECT") => void }) {
  const expires = new Date(a.expires_at);
  return (
    <div className="card stack" role="region" aria-label="변경 승인 요청" style={{ borderLeft: "3px solid var(--color-warning)" }}>
      <div className="row">
        <span className="badge warning">확인 요청</span>
        <h4 style={{ margin: 0 }}>{TOOL_LABEL[a.tool_name] ?? a.tool_name}</h4>
        <span className="spacer" />
        <span className="muted">만료 {expires.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}</span>
      </div>
      <div className="muted">이도현 님이 담당 섹션에 초안을 넣기 전에 확인을 요청했습니다 · 대상: {SECTIONS.find((x) => x.id === a.before_after.section)?.title ?? "태스크"}</div>
      {a.tool_name === "patch_artifact_section" ? (
        <div className="diff">
          <div><div className="muted">이전</div><pre>{a.before_after.before || "(비어 있음)"}</pre></div>
          <div><div className="muted">이후</div><pre>{a.before_after.after}</pre></div>
        </div>
      ) : (
        <div className="diff">
          <div><div className="muted">이전</div><pre>{a.before_after.before}</pre></div>
          <div><div className="muted">이후</div><pre>{a.before_after.after}</pre></div>
        </div>
      )}
      <div className="row">
        <button className="btn btn-primary" disabled={busy} onClick={() => onDecide("APPROVE")}>승인</button>
        <button className="btn" disabled={busy} onClick={() => onDecide("REJECT")}>거절</button>
      </div>
    </div>
  );
}
