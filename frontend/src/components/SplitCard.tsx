"use client";
import { useEffect, useState } from "react";
import type { SplitProposal } from "@/lib/types";

type Props = {
  proposal: SplitProposal;
  active: boolean;     // 분업이 아직 확정 전이고 입력 가능할 때만 조작
  confirmed: boolean;
  rounds: number; maxRounds: number;
  onPropose: (p: SplitProposal) => Promise<void>;
};
const WHO = [["CANDIDATE", "나"], ["COLLEAGUE", "한서윤"]] as const;

/** E0 분업 카드: 안내문·리워드 표 담당과 FAQ 5개 배분을 정해 서윤 님에게 제안한다(최대 3라운드). */
export function SplitCard({ proposal, active, confirmed, rounds, maxRounds, onPropose }: Props) {
  const [draft, setDraft] = useState<SplitProposal>(proposal);
  const [busy, setBusy] = useState(false);
  useEffect(() => setDraft(proposal), [proposal]);

  async function submit() {
    setBusy(true);
    try { await onPropose(draft); } finally { setBusy(false); }
  }
  const sel = (key: "T1" | "T3", label: string) => (
    <tr>
      <td>{label}</td>
      <td>{active ? (
        <select className="select" aria-label={`${label} 담당`} value={draft[key]}
          onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value as SplitProposal["T1"] }))}>
          {WHO.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>) : <span>{WHO.find(([v]) => v === proposal[key])?.[1]}</span>}</td>
    </tr>
  );
  return (
    <div className="card stack" role="group" aria-label="업무 분담">
      <div className="row">
        <h4>업무 분담</h4><span className="spacer" />
        {confirmed ? <span className="badge success">확정됨</span> : <span className="badge warning">논의 중 · {rounds}/{maxRounds}회 제안</span>}
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>태스크</th><th style={{ width: 140 }}>담당</th></tr></thead>
          <tbody>
            {sel("T1", "T1 앱 공지용 안내문")}
            {sel("T3", "T3 리워드·일정 표")}
            <tr>
              <td>T2 고객 FAQ 5개</td>
              <td>{active ? (
                <select className="select" aria-label="FAQ 중 내가 맡을 개수" value={draft.faq_candidate}
                  onChange={(e) => setDraft((d) => ({ ...d, faq_candidate: Number(e.target.value) }))}>
                  {[0, 1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>나 {n} · 서윤 {5 - n}</option>)}
                </select>) : <span>나 {proposal.faq_candidate} · 서윤 {5 - proposal.faq_candidate}</span>}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {active && (
        <div className="row">
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={submit}>이렇게 나눠요</button>
          <span className="muted">서윤 님이 답한 뒤 확정됩니다. 확정된 담당은 태스크 보드에 반영됩니다.</span>
        </div>
      )}
    </div>
  );
}
