"use client";
import { useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Modal } from "@/components/Overlay";
import { api, ApiError } from "@/lib/api";
import { COPY, fmtTime, SECTIONS, type Artifact } from "@/lib/types";

export type SaveState = "idle" | "dirty" | "saving" | "saved" | "conflict" | "failed";
type Props = {
  sessionId: string;
  artifact: Artifact;
  readOnly: boolean;
  onSaved: (a: Artifact) => void;
  reloadArtifact: () => Promise<Artifact | null>;
  onSaveState: (s: { state: SaveState; savedAt: string | null }) => void;
};

function SaveLabel({ st, at }: { st: SaveState; at?: string | null }) {
  if (st === "saving") return <span className="row small" aria-live="polite"><span className="spin" aria-hidden="true" />{COPY.saving}</span>;
  if (st === "saved") return <span className="row small" aria-live="polite" style={{ color: "#15803d" }}><Icon name="check" />{COPY.saved}{at ? ` · ${at}` : ""}</span>;
  if (st === "dirty") return <span className="small muted">수정됨</span>;
  if (st === "failed") return <span className="row small" style={{ color: "var(--color-error)" }}><Icon name="error" />저장하지 못했습니다</span>;
  if (st === "conflict") return <span className="row small" style={{ color: "#b45309" }}><Icon name="warning" />충돌 확인 필요</span>;
  return null;
}

/** 5섹션 기획안 (DESIGN_GUIDE §4.8, §6.10, §10.5). 성공 응답 후에만 '저장됨'. */
export function ArtifactEditor({ sessionId, artifact, readOnly, onSaved, reloadArtifact, onSaveState }: Props) {
  const [local, setLocal] = useState<Record<string, string>>(artifact.sections);
  const [state, setState] = useState<Record<string, SaveState>>({});
  const [savedAt, setSavedAt] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState<{ section: string; remote: string } | null>(null);
  const server = useRef(artifact);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const dirty = useRef<Set<string>>(new Set());
  const reqSeq = useRef<Record<string, number>>({});

  useEffect(() => {
    server.current = artifact;
    setLocal((prev) => {
      const next = { ...prev };
      for (const s of SECTIONS) if (!dirty.current.has(s.id)) next[s.id] = artifact.sections[s.id] ?? "";
      return next;
    });
  }, [artifact]);

  useEffect(() => {
    const vals = Object.values(state);
    const agg: SaveState = vals.includes("conflict") ? "conflict" : vals.includes("failed") ? "failed" : vals.includes("saving") ? "saving"
      : vals.includes("dirty") ? "dirty" : vals.includes("saved") ? "saved" : "idle";
    const last = Object.values(savedAt).sort().pop() ?? null;
    onSaveState({ state: agg, savedAt: last });
  }, [state, savedAt, onSaveState]);

  async function save(section: string, content: string, retried = false) {
    const my = (reqSeq.current[section] = (reqSeq.current[section] ?? 0) + 1);
    setState((s) => ({ ...s, [section]: "saving" }));
    try {
      const r = await api<{ artifact: Artifact }>(`/sessions/${sessionId}/artifact`, {
        method: "PATCH", json: { base_version: server.current.version, section, content, source_refs: [] },
      });
      server.current = r.artifact;
      onSaved(r.artifact);
      if (reqSeq.current[section] !== my) return; // 오래된 응답이 최신 draft를 덮지 않게
      dirty.current.delete(section);
      setSavedAt((m) => ({ ...m, [section]: fmtTime(new Date().toISOString()) }));
      setState((s) => ({ ...s, [section]: "saved" }));
    } catch (e) {
      if (e instanceof ApiError && e.code === "VERSION_CONFLICT") {
        const before = server.current.sections[section] ?? "";
        const latest = await reloadArtifact();
        if (latest) {
          server.current = latest;
          if (!retried && (latest.sections[section] ?? "") === before) return save(section, content, true); // 다른 섹션만 바뀜
          setConflict({ section, remote: latest.sections[section] ?? "" });
        }
        setState((s) => ({ ...s, [section]: "conflict" }));
      } else {
        setState((s) => ({ ...s, [section]: "failed" }));
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

  function resolve(keepMine: boolean) {
    if (!conflict) return;
    const { section } = conflict;
    setConflict(null);
    if (keepMine) save(section, local[section], true);
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
        const val = local[s.id] ?? "";
        return (
          <section key={s.id} className="section-card" id={`section-${s.id}`} aria-labelledby={`sec-title-${s.id}`}>
            <div className="row"><h3 id={`sec-title-${s.id}`}>{s.title}</h3><span className="spacer" />{!val.trim() && <span className="badge">비어 있음</span>}</div>
            <label htmlFor={`sec-${s.id}`} className="sr-only">{s.title}</label>
            <textarea id={`sec-${s.id}`} className="textarea" value={val} readOnly={readOnly} placeholder={s.hint}
              aria-describedby={`sec-foot-${s.id}`} onChange={(e) => onChange(s.id, e.target.value)} />
            <div className="section-foot" id={`sec-foot-${s.id}`}>
              <SaveLabel st={st} at={savedAt[s.id]} />
              {st === "failed" && <button className="btn btn-sm" onClick={() => save(s.id, val)}>다시 시도</button>}
              <span className="spacer" />
              <span className="muted num">{val.length.toLocaleString()}자</span>
            </div>
            {st === "failed" && <p className="help">{COPY.save_failed}</p>}
          </section>
        );
      })}
      <Modal open={!!conflict} size="lg" title="다른 변경이 먼저 저장되었습니다"
        description="내 입력과 최신 저장본을 모두 보존했습니다. 자동으로 덮어쓰지 않습니다." onClose={() => resolve(false)}
        footer={<><button className="btn" onClick={() => resolve(false)}>최신 버전으로 다시 열기</button><button className="btn btn-primary" data-autofocus onClick={() => resolve(true)}>내 입력으로 저장</button></>}>
        {conflict && (
          <div className="stack">
            <p className="strong">{SECTIONS.find((x) => x.id === conflict.section)?.title}</p>
            <div className="diff">
              <div><span className="small strong">최신 저장본</span><pre className="expanded">{conflict.remote || "(비어 있음)"}</pre></div>
              <div><span className="small strong">내 입력</span><pre className="expanded">{local[conflict.section] || "(비어 있음)"}</pre></div>
            </div>
            <button className="btn btn-sm" onClick={() => navigator.clipboard.writeText(local[conflict.section] ?? "")}>내 입력 복사</button>
          </div>
        )}
      </Modal>
    </div>
  );
}
