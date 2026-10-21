"use client";
import { useState } from "react";
import { Icon } from "@/components/Icon";
import { api, ApiError } from "@/lib/api";
import { ARTIFACT_HINT, COPY, ERROR_COPY, type Artifact } from "@/lib/types";

/** 내 산출물 편집기(T1~T5). 자동 저장 없이 '저장'을 눌러야 저장된다 — 저장은 시험 시계를 앞당기지 않는다. */
export function ArtifactEditor({ sessionId, artifacts, readOnly, onSaved }: {
  sessionId: string; artifacts: Artifact[]; readOnly: boolean; onSaved: (a: Artifact) => void;
}) {
  const [active, setActive] = useState<string>(artifacts[0]?.key ?? "T1");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [state, setState] = useState<Record<string, "saving" | "saved" | "failed" | "conflict">>({});
  const [error, setError] = useState<string | null>(null);
  const a = artifacts.find((x) => x.key === active) ?? artifacts[0];

  // 서버 본문(서윤 수정안 승인 포함)은 내가 고치는 중이 아닐 때(draft 없음) 그대로 보인다
  if (!a) return null;
  const value = draft[a.key] ?? a.body;
  const dirty = draft[a.key] !== undefined && draft[a.key] !== a.body;

  async function save() {
    if (!a) return;
    setState((s) => ({ ...s, [a.key]: "saving" })); setError(null);
    try {
      const r = await api<{ artifact: Artifact }>(`/sessions/${sessionId}/artifacts/${a.key}`, {
        method: "PATCH", json: { base_version: a.version, body: value },
      });
      onSaved(r.artifact);
      setDraft((d) => { const n = { ...d }; delete n[a.key]; return n; });
      setState((s) => ({ ...s, [a.key]: "saved" }));
    } catch (e) {
      const conflict = e instanceof ApiError && e.code === "VERSION_CONFLICT";
      setState((s) => ({ ...s, [a.key]: conflict ? "conflict" : "failed" }));
      setError(e instanceof ApiError ? (ERROR_COPY[e.code] ?? e.message) : COPY.save_failed);
    }
  }

  const st = state[a.key];
  return (
    <div className="stack">
      <div className="tabs" role="tablist" aria-label="내 산출물">
        {artifacts.map((x) => (
          <button key={x.key} role="tab" className="tab" aria-selected={x.key === a.key} onClick={() => setActive(x.key)}>
            {x.key}{x.change && <span className="badge num">v{x.version} · 변경</span>}{draft[x.key] !== undefined && draft[x.key] !== x.body ? " •" : ""}
          </button>
        ))}
      </div>
      <section className="section-card" aria-labelledby={`art-${a.key}`}>
        <div className="row"><h3 id={`art-${a.key}`}>{a.key} {a.title}</h3><span className="spacer" /><span className="badge num">v{a.version}</span></div>
        <p className="help">{ARTIFACT_HINT[a.key]}</p>
        {a.change && <details className="alert info" open><summary>서윤 문서 수정 · v{a.change.version}</summary>
          <div style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}><del>{a.change.before || "(없음)"}</del><span aria-label="에서 다음으로"> → </span><ins>{a.change.after || "(삭제)"}</ins></div>
        </details>}
        <label htmlFor={`art-body-${a.key}`} className="sr-only">{a.title}</label>
        <textarea id={`art-body-${a.key}`} className="textarea" value={value} readOnly={readOnly}
          onChange={(e) => { const v = e.target.value; setDraft((d) => ({ ...d, [a.key]: v })); setState((s) => { const n = { ...s }; delete n[a.key]; return n; }); }} />
        <div className="section-foot">
          {st === "saving" && <span className="row small"><span className="spin" aria-hidden="true" />{COPY.saving}</span>}
          {st === "saved" && !dirty && <span className="row small" style={{ color: "#15803d" }}><Icon name="check" />{COPY.saved}</span>}
          {dirty && <span className="small muted">저장하지 않은 변경</span>}
          <span className="spacer" />
          <span className="muted num">{value.length.toLocaleString()}자</span>
          {!readOnly && <button className="btn btn-primary btn-sm" disabled={!dirty || st === "saving"} onClick={save}>저장</button>}
        </div>
        {error && (st === "failed" || st === "conflict") && <p className="field-error" role="alert">{error}</p>}
      </section>
    </div>
  );
}
