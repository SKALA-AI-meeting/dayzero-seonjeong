"use client";
import { useState } from "react";
import { OWNER_LABEL, SECTIONS, type Owner, type SplitProposal } from "@/lib/types";

type Props = {
  proposal: SplitProposal;
  active: boolean; // 최신 제안이고 아직 확정 전일 때만 조작 가능
  confirmed: boolean;
  onDecide: (decision: "ACCEPT" | "ADJUST", assignments: Record<string, Owner>) => Promise<void>;
};

const OWNERS: Owner[] = ["CANDIDATE", "JOINT", "COLLEAGUE"];

export function SplitCard({ proposal, active, confirmed, onDecide }: Props) {
  const [draft, setDraft] = useState<Record<string, Owner>>(proposal.assignments);
  const [busy, setBusy] = useState(false);
  const changed = SECTIONS.some((s) => draft[s.id] !== proposal.assignments[s.id]);
  const left = proposal.max_adjustments - proposal.adjustments_used;

  async function act(decision: "ACCEPT" | "ADJUST") {
    setBusy(true);
    try { await onDecide(decision, decision === "ACCEPT" ? proposal.assignments : draft); } finally { setBusy(false); }
  }

  return (
    <div className="card stack" style={{ marginTop: 8 }} role="group" aria-label="업무 분담안">
      <h4 style={{ margin: 0 }}>업무 분담안</h4>
      <table>
        <tbody>
          {SECTIONS.map((s) => (
            <tr key={s.id}>
              <td>{s.title}</td>
              <td style={{ width: 120 }}>
                {active ? (
                  <select aria-label={`${s.title} 담당`} value={draft[s.id]} onChange={(e) => setDraft((d) => ({ ...d, [s.id]: e.target.value as Owner }))}>
                    {OWNERS.map((o) => <option key={o} value={o}>{OWNER_LABEL[o]}</option>)}
                  </select>
                ) : <span>{OWNER_LABEL[proposal.assignments[s.id]]}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {active ? (
        <div className="row">
          {changed
            ? <button className="btn btn-primary btn-sm" disabled={busy || left <= 0} onClick={() => act("ADJUST")}>이렇게 다시 나누자고 제안</button>
            : <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => act("ACCEPT")}>이 분담으로 확정</button>}
          {changed && <button className="btn btn-sm" disabled={busy} onClick={() => setDraft(proposal.assignments)}>되돌리기</button>}
          <span className="muted">조정 {left}회 남음</span>
        </div>
      ) : (
        <span className={`badge ${confirmed ? "success" : ""}`}>{confirmed ? "확정됨" : "이전 제안"}</span>
      )}
    </div>
  );
}
