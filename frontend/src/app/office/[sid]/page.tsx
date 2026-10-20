"use client";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApprovalCard } from "@/components/ApprovalCard";
import { ArtifactEditor } from "@/components/ArtifactEditor";
import { Chat } from "@/components/Chat";
import { api, ApiError, loadMe, uuid } from "@/lib/api";
import { subscribe, type StreamEvent } from "@/lib/events";
import { TASK_STATUS, type Artifact, type Citation, type DelegationProposal, type Snapshot, type Task } from "@/lib/types";

type Doc = { id: string; title: string; version: number; body?: string };
const TOOL_NAME: Record<string, string> = {
  get_funnel_metrics: "퍼널 지표 조회", get_support_cases: "고객 문의 조회", search_docs: "문서 검색",
  get_session_context: "업무 상태 확인", read_resource: "문서 원문 열람", patch_artifact_section: "기획안 변경", update_task_status: "태스크 상태 변경",
};

export default function Office() {
  const { sid } = useParams<{ sid: string }>();
  const router = useRouter();
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [openDoc, setOpenDoc] = useState<Doc | null>(null);
  const [quote, setQuote] = useState<string | null>(null);
  const [leftTab, setLeftTab] = useState<"docs" | "tasks">("docs");
  const [chatTab, setChatTab] = useState<"TEAM" | "ASSISTANT">("TEAM");
  const [pane, setPane] = useState<"left" | "chat" | "doc">("chat");
  const [progress, setProgress] = useState<string | null>(null);
  const [failedRun, setFailedRun] = useState<string | null>(null);
  const [conn, setConn] = useState<"open" | "reconnecting">("open");
  const [error, setError] = useState<string | null>(null);
  const [busyApproval, setBusyApproval] = useState(false);
  const [confirmed] = useState<Set<string>>(new Set());
  const [submitOpen, setSubmitOpen] = useState(false);
  const [reviewComment, setReviewComment] = useState<Record<string, string>>({});
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const s = await api<Snapshot>(`/sessions/${sid}`);
      setSnap(s);
      if (s.session.status === "CREATED") router.replace("/join");
      return s;
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 404)) setError("이 세션에 접근할 수 없습니다. 초대 링크로 다시 입장해 주세요.");
      else setError("작업 공간을 불러오지 못했습니다. 새로고침해 주세요.");
      return null;
    }
  }, [sid, router]);

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(refresh, 150);
  }, [refresh]);

  useEffect(() => {
    let unsub: (() => void) | null = null;
    (async () => {
      await loadMe();
      const s = await refresh();
      if (!s) return;
      api<{ items: Doc[] }>(`/sessions/${sid}/documents`).then((r) => setDocs(r.items)).catch(() => undefined);
      unsub = subscribe(sid, s.session.last_stream_seq, (e: StreamEvent) => {
        const pl = e.payload as Record<string, unknown>;
        if (e.type === "RUN_STARTED") { setFailedRun(null); setProgress("동료가 요청을 확인하고 있습니다…"); }
        else if (e.type === "TOOL_START") setProgress(`${TOOL_NAME[String(pl.display_name)] ?? pl.display_name} 실행 중…`);
        else if (e.type === "TOOL_END") setProgress(`${TOOL_NAME[String(pl.display_name)] ?? "도구"} ${pl.outcome === "ok" ? "완료" : "실패"}`);
        else if (e.type === "APPROVAL_REQUIRED") setProgress("변경 승인을 기다리고 있습니다");
        else if (e.type === "DONE") setProgress(null);
        else if (e.type === "FAILED") { setProgress(null); setFailedRun(e.run_id); }
        else if (e.type === "SESSION_DONE") router.push(`/debrief/${sid}`);
        scheduleRefresh();
      }, setConn);
    })();
    return () => unsub?.();
  }, [sid, refresh, scheduleRefresh, router]);

  async function openDocument(id: string, q: string | null = null) {
    try {
      const d = await api<Doc>(`/sessions/${sid}/documents/${id}`);
      setOpenDoc(d);
      setQuote(q);
      setLeftTab("docs");
      setPane("left");
    } catch {
      setError("문서를 열지 못했습니다");
    }
  }

  async function send(channel: "TEAM" | "ASSISTANT", content: string) {
    setError(null);
    try {
      await api(`/sessions/${sid}/messages`, { method: "POST", json: { client_message_id: uuid(), channel, content } });
      scheduleRefresh();
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "메시지를 보내지 못했습니다");
      return false;
    }
  }

  async function confirmDelegation(p: DelegationProposal) {
    try {
      await api(`/sessions/${sid}/delegations`, {
        method: "POST", headers: { "Idempotency-Key": uuid() },
        json: { source_message_id: p.source_message_id, title: p.title, target_section: "evidence", allowed_tools: p.allowed_tools, filters: p.filters },
      });
      scheduleRefresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "위임을 만들지 못했습니다");
    }
  }

  async function decide(aid: string, decision: "APPROVE" | "REJECT") {
    setBusyApproval(true);
    try {
      await api(`/sessions/${sid}/approvals/${aid}/decision`, { method: "POST", json: { decision } });
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : "결정을 저장하지 못했습니다");
    } finally {
      setBusyApproval(false);
      scheduleRefresh();
    }
  }

  async function review(t: Task, decision: "ACCEPT" | "REVISE" | "REJECT") {
    try {
      const refs = (t.result?.citations ?? []).slice(0, 0); // 지원자가 직접 대조한 근거만 첨부 (기본 없음)
      await api(`/sessions/${sid}/tasks/${t.id}/review`, { method: "POST", json: { decision, comment: reviewComment[t.id] ?? "", source_refs: refs } });
      scheduleRefresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "검토 결과를 저장하지 못했습니다");
    }
  }

  async function moveTask(t: Task, status: string) {
    try {
      await api(`/sessions/${sid}/tasks/${t.id}`, { method: "PATCH", json: { base_version: t.version, status } });
      scheduleRefresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "태스크를 변경하지 못했습니다");
      scheduleRefresh();
    }
  }

  async function revoke(did: string) {
    try { await api(`/sessions/${sid}/delegations/${did}`, { method: "DELETE" }); scheduleRefresh(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "위임을 취소하지 못했습니다"); }
  }

  async function submit() {
    if (!snap?.artifact) return;
    try {
      await api(`/sessions/${sid}/submit`, { method: "POST", json: { base_version: snap.artifact.version, summary: "" } });
      router.push(`/debrief/${sid}`);
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : "제출하지 못했습니다");
      setSubmitOpen(false);
      scheduleRefresh();
    }
  }

  async function retryRun(rid: string) {
    try { await api(`/runs/${rid}/retry`, { method: "POST", json: {} }); setFailedRun(null); }
    catch (e) { setError(e instanceof ApiError ? e.message : "재시도하지 못했습니다"); }
  }

  if (error && !snap) return <main className="center-card card"><div className="alert error" role="alert">{error}</div></main>;
  if (!snap || !snap.artifact) return <main className="center-card card"><p className="muted">작업 공간을 불러오는 중…</p></main>;

  const submitted = snap.session.status === "SUBMITTED";
  const emptySections = Object.entries(snap.artifact.sections).filter(([, v]) => !v.trim()).map(([k]) => k);
  const run = snap.active_run;
  const busy = !!run && ["QUEUED", "RUNNING", "WAITING_APPROVAL"].includes(run.status);
  const proposalsDone = new Set(snap.messages.filter((m) => m.meta?.delegation_proposal && snap.tasks.some((t) => t.owner === "COLLEAGUE" && t.title === m.meta.delegation_proposal!.title)).map((m) => m.id));
  const highlightDoc = (body: string) => {
    if (!quote) return body;
    const i = body.indexOf(quote);
    if (i < 0) return body;
    return <>{body.slice(0, i)}<mark>{body.slice(i, i + quote.length)}</mark>{body.slice(i + quote.length)}</>;
  };

  return (
    <>
      <header className="topbar">
        <span className="brand"><span className="brand-dot" />{snap.brief.service_name} · {snap.brief.title}</span>
        <span className="badge info">{snap.mode === "live" ? "LIVE · gpt-4o-mini" : "DEMO · fixture 모드"}</span>
        <span className="spacer" />
        <span className={`badge ${conn === "open" ? "success" : "warning"}`}>{conn === "open" ? "실시간 연결됨" : "재연결 중…"}</span>
        <span className={`badge ${submitted ? "success" : "info"}`}>{submitted ? "제출 완료" : `진행 중 · 기획안 v${snap.artifact.version}`}</span>
        {!submitted && <button className="btn btn-primary" onClick={() => setSubmitOpen(true)}>제출</button>}
      </header>
      <nav className="mobile-tabs tabs" role="tablist">
        {(["left", "chat", "doc"] as const).map((k) => (
          <button key={k} role="tab" className="tab" aria-selected={pane === k} onClick={() => setPane(k)}>{k === "left" ? "자료·태스크" : k === "chat" ? "채팅" : "기획안"}</button>
        ))}
      </nav>
      {error && <div className="alert error" role="alert" style={{ margin: "8px 16px" }}>{error} <button className="btn btn-sm" onClick={() => setError(null)}>닫기</button></div>}
      {submitOpen && (
        <div className="card stack" role="dialog" aria-label="제출 확인" style={{ margin: "8px 16px" }}>
          <h3>기획안을 제출할까요?</h3>
          {emptySections.length > 0 && <div className="alert warning">비어 있는 섹션: {emptySections.join(", ")}. 그대로 제출할 수 있으며, 빈 섹션이라는 사실만 기록됩니다.</div>}
          <p className="muted">제출하면 기획안이 고정되고 진행 중인 동료 작업과 승인 대기는 종료됩니다.</p>
          <div className="row"><button className="btn btn-primary" onClick={submit}>제출 확정</button><button className="btn" onClick={() => setSubmitOpen(false)}>계속 작업</button></div>
        </div>
      )}
      <main className="office">
        <section className={`pane ${pane === "left" ? "active" : ""}`} aria-label="자료와 태스크">
          <div className="pane-head tabs" role="tablist">
            <button role="tab" className="tab" aria-selected={leftTab === "docs"} onClick={() => setLeftTab("docs")}>기본 자료</button>
            <button role="tab" className="tab" aria-selected={leftTab === "tasks"} onClick={() => setLeftTab("tasks")}>태스크 보드</button>
          </div>
          <div className="pane-body stack">
            {leftTab === "docs" && (openDoc ? (
              <div className="stack">
                <button className="btn btn-sm" onClick={() => { setOpenDoc(null); setQuote(null); }}>← 목록</button>
                <h3>{openDoc.title} <span className="muted">v{openDoc.version}</span></h3>
                <div className="doc-body">{highlightDoc(openDoc.body ?? "")}</div>
              </div>
            ) : (
              <>
                <div className="card"><h4>과제 브리프</h4><p style={{ margin: 0 }}>{snap.brief.public_brief}</p></div>
                {docs.length === 0 && <p className="muted">자료를 불러오는 중…</p>}
                {docs.map((d) => <button key={d.id} className="doc-item" onClick={() => openDocument(d.id)}>{d.title}<div className="muted">{d.id} · v{d.version}</div></button>)}
              </>
            ))}
            {leftTab === "tasks" && snap.tasks.map((t) => (
              <div key={t.id} className="task stack">
                <div className="row"><strong style={{ color: "var(--color-heading)" }}>{t.title}</strong><span className="spacer" /><span className={`badge ${TASK_STATUS[t.status]?.[1]}`}>{TASK_STATUS[t.status]?.[0]}</span></div>
                <div className="muted">담당: {t.owner === "CANDIDATE" ? "나" : "이도현(AI 동료)"}{t.target_section ? ` · ${t.target_section}` : ""}</div>
                {t.owner === "CANDIDATE" && !submitted && (
                  <div className="row">
                    {t.status === "TODO" && <button className="btn btn-sm" onClick={() => moveTask(t, "IN_PROGRESS")}>시작</button>}
                    {t.status === "IN_PROGRESS" && <button className="btn btn-sm" onClick={() => moveTask(t, "DONE")}>완료</button>}
                    {t.status === "DONE" && <button className="btn btn-sm" onClick={() => moveTask(t, "IN_PROGRESS")}>다시 열기</button>}
                  </div>
                )}
                {t.owner === "COLLEAGUE" && t.result?.summary && <div className="doc-body card" style={{ padding: 8 }}>{t.result.summary}</div>}
                {t.owner === "COLLEAGUE" && t.status === "REVIEW" && !submitted && (
                  <div className="stack">
                    <textarea className="textarea" style={{ minHeight: 50 }} placeholder="검토 메모(선택)" aria-label="검토 메모" value={reviewComment[t.id] ?? ""} onChange={(e) => setReviewComment((c) => ({ ...c, [t.id]: e.target.value }))} />
                    <div className="row"><button className="btn btn-sm btn-primary" onClick={() => review(t, "ACCEPT")}>수락</button><button className="btn btn-sm" onClick={() => review(t, "REVISE")}>수정 요청</button><button className="btn btn-sm" onClick={() => review(t, "REJECT")}>기각</button></div>
                  </div>
                )}
                {t.owner === "COLLEAGUE" && t.delegation_id && ["TODO", "IN_PROGRESS"].includes(t.status) && !submitted && <button className="btn btn-sm" onClick={() => revoke(t.delegation_id!)}>위임 취소</button>}
              </div>
            ))}
          </div>
        </section>
        <section className={`pane ${pane === "chat" ? "active" : ""}`} aria-label="채팅" style={{ display: undefined }}>
          <div className="chat" style={{ height: "100%" }}>
            <div className="pane-head tabs" role="tablist">
              <button role="tab" className="tab" aria-selected={chatTab === "TEAM"} onClick={() => setChatTab("TEAM")}>팀 채팅</button>
              <button role="tab" className="tab" aria-selected={chatTab === "ASSISTANT"} onClick={() => setChatTab("ASSISTANT")}>어시스턴트</button>
              <span className="spacer" />
              {busy && <span className="badge info">{run?.status === "WAITING_APPROVAL" ? "승인 대기" : "동료 작업 중"}</span>}
            </div>
            <Chat channel={chatTab} messages={snap.messages} progress={progress} busy={busy} disabled={submitted}
              failedRunId={failedRun} onSend={(t) => send(chatTab, t)} onRetry={retryRun}
              onOpenCitation={(c: Citation) => openDocument(c.document_id, c.quote)} onConfirmDelegation={confirmDelegation}
              confirmedProposals={new Set([...confirmed, ...proposalsDone])} />
          </div>
        </section>
        <section className={`pane ${pane === "doc" ? "active" : ""}`} aria-label="개선 기획안">
          <div className="pane-head"><h3 style={{ margin: 0 }}>개선 기획안</h3><span className="spacer" /><span className="muted">문제 정의·우선순위·최종안은 직접 결정합니다</span></div>
          <div className="pane-body stack">
            {snap.approvals.map((a) => <ApprovalCard key={a.id} a={a} busy={busyApproval} onDecide={(d) => decide(a.id, d)} />)}
            <ArtifactEditor sessionId={sid} artifact={snap.artifact} readOnly={submitted} highlight={null}
              onSaved={(a: Artifact) => setSnap((s) => (s ? { ...s, artifact: a } : s))}
              reloadArtifact={async () => (await refresh())?.artifact ?? null} />
          </div>
        </section>
      </main>
    </>
  );
}
