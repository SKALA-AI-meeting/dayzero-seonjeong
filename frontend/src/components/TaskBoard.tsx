"use client";
import { useState } from "react";
import { ACTOR, OWNER_LABEL, TASK_STATUS, type Task } from "@/lib/types";

type Patch = { status?: string; owner?: "CANDIDATE" | "COLLEAGUE"; eta?: string };

/** 태스크 보드: 담당·상태·예상 완료 시각. 변경 1번이 1턴이다(설계서 4장). */
export function TaskBoard({ tasks, readOnly, onPatch }: { tasks: Task[]; readOnly: boolean; onPatch: (t: Task, p: Patch) => void }) {
  const [eta, setEta] = useState<Record<string, string>>({});
  return (
    <div className="stack">
      {tasks.map((t) => {
        const a = t.owner === "COLLEAGUE" ? ACTOR.COLLEAGUE : t.owner === "CANDIDATE" ? ACTOR.CANDIDATE : null;
        const draftEta = eta[t.key] ?? t.eta ?? "";
        return (
          <article key={t.id} className="task-card stack">
            <div className="row">
              <span className="badge">{t.key}</span>
              <strong style={{ color: "var(--color-heading)", flex: 1, minWidth: 0 }}>{t.title}</strong>
              <span className={`badge ${TASK_STATUS[t.status]?.[1] ?? ""}`}>{TASK_STATUS[t.status]?.[0] ?? t.status}</span>
            </div>
            <div className="row small">
              <span className="owner">{a && <span className={`avatar ${a.avatar}`} aria-hidden="true">{a.initial}</span>}담당 {OWNER_LABEL[t.owner]}</span>
              {t.eta && <span className="badge num">예상 {t.eta}</span>}
              {t.note && <span className="muted">{t.note}</span>}
            </div>
            {!readOnly && (
              <div className="row">
                <select className="select" aria-label={`${t.key} 담당`} value={t.owner === "SPLIT" || t.owner === "UNASSIGNED" ? "" : t.owner}
                  onChange={(e) => e.target.value && onPatch(t, { owner: e.target.value as "CANDIDATE" | "COLLEAGUE" })}>
                  <option value="" disabled>담당 지정</option>
                  <option value="CANDIDATE">나</option>
                  <option value="COLLEAGUE">한서윤</option>
                </select>
                <select className="select" aria-label={`${t.key} 상태`} value={t.status} onChange={(e) => onPatch(t, { status: e.target.value })}>
                  {Object.entries(TASK_STATUS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
                </select>
                <input className="input" style={{ width: 84, minHeight: 32, padding: "4px 8px" }} aria-label={`${t.key} 예상 완료 시각`}
                  placeholder="예: 11:00" maxLength={20} value={draftEta} onChange={(e) => setEta((m) => ({ ...m, [t.key]: e.target.value }))} />
                <button className="btn btn-sm" disabled={!draftEta.trim() || draftEta === (t.eta ?? "")}
                  onClick={() => onPatch(t, { eta: draftEta.trim() })}>시각 기록</button>
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
