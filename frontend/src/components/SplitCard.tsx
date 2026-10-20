"use client";
import { useState } from "react";
import { OWNER_SHORT, SECTIONS, type Owner, type SplitProposal } from "@/lib/types";

type Props = {
  proposal: SplitProposal;
  active: boolean; // 최신 제안이고 아직 확정 전일 때만 조작 가능
  confirmed: boolean;
  onDecide: (decision: "ACCEPT" | "ADJUST", assignments: Record<string, Owner>) => Promise<void>;
  // 조정과 확정은 한 번에: 바뀐 분담으로 확정하면 서버가 조정 이력을 남긴다
};
const OWNERS: Owner[] = ["CANDIDATE", "JOINT", "COLLEAGUE"];

export function SplitCard({ proposal, active, confirmed, onDecide }: Props) {
  const [draft, setDraft] = useState<Record<string, Owner>>(proposal.assignments);
  const [busy, setBusy] = useState(false);
  const changed = SECTIONS.some((s) => draft[s.id] !== proposal.assignments[s.id]);

  async function act(kind: "ACCEPT" | "ADJUST_CONFIRM") {
    setBusy(true);
    try { await onDecide("ACCEPT", kind === "ACCEPT" ? proposal.assignments : draft); } finally { setBusy(false); }
  }

  return (
    <div className="card stack" role="group" aria-label="업무 분담안">
      <div className="row">
        <h4>업무 분담안</h4><span className="spacer" />
        {active ? <span className="badge warning">확정 전</span> : confirmed ? <span className="badge success">확정됨</span> : <span className="badge">이전 제안</span>}
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>기획안 섹션</th><th style={{ width: 120 }}>담당</th></tr></thead>
          <tbody>
            {SECTIONS.map((s) => (
              <tr key={s.id}>
                <td>{s.title}</td>
                <td>
                  {active ? (
                    <select className="select" aria-label={`${s.title} 담당`} value={draft[s.id]}
                      onChange={(e) => setDraft((d) => ({ ...d, [s.id]: e.target.value as Owner }))}>
                      {OWNERS.map((o) => <option key={o} value={o}>{OWNER_SHORT[o]}</option>)}
                    </select>
                  ) : <span>{OWNER_SHORT[proposal.assignments[s.id]]}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {active && (
        <div className="row">
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => act(changed ? "ADJUST_CONFIRM" : "ACCEPT")}>
            {changed ? "바꾼 분담으로 확정" : "이 분담으로 확정"}</button>
          {changed && <button className="btn btn-sm" disabled={busy} onClick={() => setDraft(proposal.assignments)}>제안대로 되돌리기</button>}
          <span className="muted">담당을 바꾼 뒤 확정하면 이도현 님이 맞춰 진행하고, 확정한 담당은 태스크 보드에 반영됩니다</span>
        </div>
      )}
    </div>
  );
}
