"use client";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { SECTIONS, type Artifact } from "@/lib/types";

type SaveState = "idle" | "dirty" | "saving" | "saved" | "conflict" | "error";
const SAVE_LABEL: Record<SaveState, [string, string]> = {
  idle: ["변경 없음", ""], dirty: ["저장 대기", "warning"], saving: ["저장 중…", "info"],
  saved: ["저장됨", "success"], conflict: ["충돌: 확인 필요", "error"], error: ["저장 실패", "error"],
};

type Props = {
  sessionId: string;
  artifact: Artifact;
  readOnly: boolean;
  highlight: string | null;
  onSaved: (a: Artifact) => void;
  reloadArtifact: () => Promise<Artifact | null>;
};

export function ArtifactEditor({ sessionId, artifact, readOnly, highlight, onSaved, reloadArtifact }: Props) {
  const [local, setLocal] = useState<Record<string, string>>(artifact.sections);
  const [state, setState] = useState<Record<string, SaveState>>({});
  const [conflict, setConflict] = useState<Record<string, string>>({});
  const server = useRef(artifact);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const dirty = useRef<Set<string>>(new Set());

  // 서버 측 변경(승인된 AI 반영 등)은 사용자가 편집 중이 아닌 섹션에만 반영
  useEffect(() => {
    server.current = artifact;
    setLocal((prev) => {
      const next = { ...prev };
      for (const s of SECTIONS) if (!dirty.current.has(s.id)) next[s.id] = artifact.sections[s.id] ?? "";
      return next;
    });
  }, [artifact]);

  async function save(section: string, content: string, retried = false) {
    setState((s) => ({ ...s, [section]: "saving" }));
    try {
      const r = await api<{ artifact: Artifact }>(`/sessions/${sessionId}/artifact`, {
        method: "PATCH",
        json: { base_version: server.current.version, section, content, source_refs: [] },
      });
      server.current = r.artifact;
      dirty.current.delete(section);
      onSaved(r.artifact);
      setState((s) => ({ ...s, [section]: "saved" }));
    } catch (e) {
      if (e instanceof ApiError && e.code === "VERSION_CONFLICT") {
        const latest = await reloadArtifact();
        if (latest) {
          const before = server.current.sections[section] ?? "";
          server.current = latest;
          // 다른 섹션만 바뀐 경우 자동으로 새 버전에 다시 저장
          if (!retried && (latest.sections[section] ?? "") === before) return save(section, content, true);
          setConflict((c) => ({ ...c, [section]: latest.sections[section] ?? "" }));
        }
        setState((s) => ({ ...s, [section]: "conflict" }));
      } else {
        setState((s) => ({ ...s, [section]: "error" }));
      }
    }
  }

  function onChange(section: string, value: string) {
    setLocal((l) => ({ ...l, [section]: value }));
    dirty.current.add(section);
    setState((s) => ({ ...s, [section]: "dirty" }));
    clearTimeout(timers.current[section]);
    timers.current[section] = setTimeout(() => save(section, value), 800);
  }

  function resolve(section: string, keepMine: boolean) {
    const mine = local[section];
    setConflict((c) => { const n = { ...c }; delete n[section]; return n; });
    if (keepMine) save(section, mine, true);
    else {
      dirty.current.delete(section);
      setLocal((l) => ({ ...l, [section]: server.current.sections[section] ?? "" }));
      setState((s) => ({ ...s, [section]: "idle" }));
    }
  }

  return (
    <div>
      {SECTIONS.map((s) => {
        const st = state[s.id] ?? "idle";
        return (
          <div key={s.id} className={`section ${highlight === s.id ? "highlight" : ""}`} id={`section-${s.id}`}>
            <div className="row">
              <label htmlFor={`sec-${s.id}`} style={{ margin: 0 }}>{s.title} <span className="muted">({s.id})</span></label>
              <span className="spacer" />
              <span className={`badge ${SAVE_LABEL[st][1]}`}>{SAVE_LABEL[st][0]}</span>
              {st === "error" && <button className="btn btn-sm" onClick={() => save(s.id, local[s.id])}>다시 저장</button>}
            </div>
            <p className="muted" style={{ margin: "2px 0 6px" }}>{s.hint}</p>
            <textarea id={`sec-${s.id}`} className="textarea" value={local[s.id] ?? ""} readOnly={readOnly}
              onChange={(e) => onChange(s.id, e.target.value)} />
            {conflict[s.id] !== undefined && (
              <div className="alert warning stack" role="alert">
                <div>다른 변경이 먼저 저장되었습니다. 내 입력은 보존되어 있습니다.</div>
                <div className="diff"><div><div className="muted">최신 저장본</div><pre>{conflict[s.id] || "(비어 있음)"}</pre></div><div><div className="muted">내 입력</div><pre>{local[s.id] || "(비어 있음)"}</pre></div></div>
                <div className="row"><button className="btn btn-sm btn-primary" onClick={() => resolve(s.id, true)}>내 입력으로 저장</button><button className="btn btn-sm" onClick={() => resolve(s.id, false)}>최신 저장본 사용</button></div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
