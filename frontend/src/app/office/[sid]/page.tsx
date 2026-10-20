"use client";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApprovalCard } from "@/components/ApprovalCard";
import { ArtifactEditor, type SaveState } from "@/components/ArtifactEditor";
import { Icon } from "@/components/Icon";
import { Messenger, type RunView } from "@/components/Messenger";
import { Drawer, Modal } from "@/components/Overlay";
import { TaskBoard } from "@/components/TaskBoard";
import { api, ApiError, loadMe, uuid } from "@/lib/api";
import { subscribe, type StreamEvent } from "@/lib/events";
import { CHANNELS, COPY, ERROR_COPY, fmtClock, SECTIONS, type Artifact, type Citation, type Owner, type Snapshot, type Task } from "@/lib/types";

type Doc = { id: string; title: string; version: number; body?: string; available?: boolean; notice?: string | null };
type Channel = "notice" | "team";
const TOOL_TEXT: Record<string, string> = {
  get_rejoin_metrics: "재참여 지표 조회 중", get_interview_notes: "인터뷰 자료 확인 중", search_docs: "회사 자료 검색 중",
  read_resource: "문서 원문 확인 중", get_session_context: "업무 상태 확인 중", patch_artifact_section: "문서 반영 중",
};

function errText(e: unknown, fallback: string) {
  return e instanceof ApiError ? (ERROR_COPY[e.code] ?? e.message) : fallback;
}

export default function Office() {
  const { sid } = useParams<{ sid: string }>();
  const router = useRouter();
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [docView, setDocView] = useState<{ doc: Doc; quote: string | null } | null>(null);
  const [briefOpen, setBriefOpen] = useState(false);
  const [briefRequired, setBriefRequired] = useState(false);
  const [submitOpen, setSubmitOpen] = useState(false);
  const [channel, setChannel] = useState<Channel>("team");
  const [workTab, setWorkTab] = useState<"doc" | "tasks" | "assistant">("doc");
  const [workOpen, setWorkOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [runs, setRuns] = useState<Record<string, RunView>>({}); // key: COLLEAGUE | ASSISTANT
  const [conn, setConn] = useState<"open" | "reconnecting">("open");
  const [toast, setToast] = useState<string | null>(null);
  const [busyApproval, setBusyApproval] = useState(false);
  const [save, setSave] = useState<{ state: SaveState; savedAt: string | null }>({ state: "idle", savedAt: null });
  const [now, setNow] = useState(() => Date.now());
  const [loadedAt, setLoadedAt] = useState(() => Date.now());
  const [noticeSeen, setNoticeSeen] = useState(0);
  const [fatal, setFatal] = useState<string | null>(null);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runKind = useRef<Record<string, string>>({});

  const refresh = useCallback(async () => {
    try {
      const s = await api<Snapshot>(`/sessions/${sid}`);
      setSnap(s);
      setLoadedAt(Date.now());
      s.active_runs.forEach((r) => { runKind.current[r.id] = r.kind; });
      if (s.session.status === "CREATED") router.replace("/join");
      return s;
    } catch (e) {
      setFatal(e instanceof ApiError && (e.status === 401 || e.status === 404)
        ? "이 작업 공간에 접근할 수 없습니다. 초대 링크로 다시 입장해 주세요." : "작업 공간을 불러오지 못했습니다. 새로고침해 주세요.");
      return null;
    }
  }, [sid, router]);
  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    refreshTimer.current = setTimeout(refresh, 150);
  }, [refresh]);
  const loadDocs = useCallback(() => {
    api<{ items: Doc[] }>(`/sessions/${sid}/documents`).then((r) => setDocs(r.items)).catch(() => undefined);
  }, [sid]);

  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => {
    let seen = false;
    try { seen = !!localStorage.getItem(`dz-brief-${sid}`); } catch { /* storage unavailable */ }
    if (!seen) { setBriefOpen(true); setBriefRequired(true); }
  }, [sid]);

  useEffect(() => {
    let unsub: (() => void) | null = null;
    (async () => {
      await loadMe();
      const s = await refresh();
      if (!s) return;
      loadDocs();
      unsub = subscribe(sid, s.session.last_stream_seq, (e: StreamEvent) => {
        const pl = e.payload as Record<string, unknown>;
        if (e.type === "RUN_STARTED" && e.run_id) runKind.current[e.run_id] = String(pl.kind);
        const key = (e.run_id && runKind.current[e.run_id]) || "";
        const setRun = (v: RunView) => { if (key === "COLLEAGUE" || key === "ASSISTANT") setRuns((r) => ({ ...r, [key]: v })); };
        if (e.type === "RUN_STARTED") setRun({ state: "running", text: COPY.investigating });
        else if (e.type === "TOOL_START") setRun({ state: "running", text: TOOL_TEXT[String(pl.display_name)] ?? COPY.investigating });
        else if (e.type === "TOOL_END") setRun({ state: "running", text: pl.outcome === "ok" ? "자료 확인 완료 · 답변 정리 중" : "일부 자료를 확인하지 못했어요 · 답변 정리 중" });
        else if (e.type === "COLLEAGUE_MESSAGE" || e.type === "ASSISTANT_MESSAGE" || e.type === "DONE") setRun(null);
        else if (e.type === "FAILED") setRun({ state: "failed", text: COPY.ai_failed, runId: e.run_id });
        else if (e.type === "SESSION_DONE") router.push(`/debrief/${sid}`);
        if (e.type === "DOCUMENTS_UPDATED" || e.type === "SYSTEM_NOTICE") loadDocs();
        scheduleRefresh();
      }, setConn);
    })();
    return () => unsub?.();
  }, [sid, refresh, scheduleRefresh, router, loadDocs]);

  async function openDocument(id: string, quote: string | null = null) {
    try {
      const d = await api<Doc>(`/sessions/${sid}/documents/${id}`);
      setDocView({ doc: d, quote });
      setNavOpen(false);
    } catch (e) { setToast(errText(e, "자료를 열지 못했습니다")); }
  }
  async function send(ch: "TEAM" | "ASSISTANT", content: string) {
    try {
      await api(`/sessions/${sid}/messages`, { method: "POST", json: { client_message_id: uuid(), channel: ch, content } });
      setRuns((r) => ({ ...r, [ch === "TEAM" ? "COLLEAGUE" : "ASSISTANT"]: { state: "running", text: ch === "TEAM" ? "요청을 전달했어요." : COPY.investigating } }));
      scheduleRefresh();
      return true;
    } catch (e) { setToast(errText(e, "메시지를 보내지 못했습니다. 입력한 내용은 그대로 남아 있습니다.")); return false; }
  }
  async function decideSplit(decision: "ACCEPT" | "ADJUST", assignments: Record<string, Owner>) {
    try { await api(`/sessions/${sid}/split`, { method: "POST", json: { decision, assignments, comment: "" } }); scheduleRefresh(); }
    catch (e) { setToast(errText(e, "업무 분담을 저장하지 못했습니다")); }
  }
  async function decide(aid: string, decision: "APPROVE" | "REJECT") {
    setBusyApproval(true);
    try { await api(`/sessions/${sid}/approvals/${aid}/decision`, { method: "POST", json: { decision } }); }
    catch (e) { setToast(errText(e, "결정을 저장하지 못했습니다")); }
    finally { setBusyApproval(false); scheduleRefresh(); }
  }
  async function review(t: Task, decision: "ACCEPT" | "REVISE" | "REJECT", comment: string) {
    try { await api(`/sessions/${sid}/tasks/${t.id}/review`, { method: "POST", json: { decision, comment, source_refs: [] } }); scheduleRefresh(); }
    catch (e) { setToast(errText(e, "검토 결과를 저장하지 못했습니다")); }
  }
  async function moveTask(t: Task, status: string) {
    try { await api(`/sessions/${sid}/tasks/${t.id}`, { method: "PATCH", json: { base_version: t.version, status } }); }
    catch (e) { setToast(errText(e, "태스크를 변경하지 못했습니다")); }
    finally { scheduleRefresh(); }
  }
  async function revoke(did: string) {
    try { await api(`/sessions/${sid}/delegations/${did}`, { method: "DELETE" }); scheduleRefresh(); }
    catch (e) { setToast(errText(e, "위임을 취소하지 못했습니다")); }
  }
  async function retryRun(rid: string) {
    try { await api(`/runs/${rid}/retry`, { method: "POST", json: {} }); setRuns((r) => ({ ...r, COLLEAGUE: null, ASSISTANT: null })); }
    catch (e) { setToast(errText(e, "재시도하지 못했습니다")); }
  }

  const messages = useMemo(() => snap?.messages ?? [], [snap]);
  const team = useMemo(() => messages.filter((m) => m.channel === "TEAM"), [messages]);
  const noticeMsgs = useMemo(() => team.filter((m) => m.actor === "MANAGER" || m.actor === "SYSTEM"), [team]);
  const assistantMsgs = useMemo(() => messages.filter((m) => m.channel === "ASSISTANT"), [messages]);
  useEffect(() => { if (channel === "notice") setNoticeSeen(noticeMsgs.length); }, [channel, noticeMsgs.length]);

  if (fatal && !snap) return <main className="center-wrap"><div className="card center-card"><div className="alert error" role="alert"><Icon name="error" />{fatal}</div></div></main>;
  if (!snap || !snap.artifact) return <main className="center-wrap"><p className="row muted"><span className="spin" />작업 공간을 불러오는 중…</p></main>;

  const submitted = snap.session.status === "SUBMITTED";
  const remaining = Math.max(0, snap.clock.remaining_min - (submitted ? 0 : (now - loadedAt) / 60000));
  const splitMsgs = messages.filter((m) => m.meta?.split_proposal);
  const activeSplitMessageId = splitMsgs.length ? splitMsgs[splitMsgs.length - 1].id : null;
  const busyFor = (k: string) => snap.active_runs.some((r) => r.kind === k && ["QUEUED", "RUNNING"].includes(r.status));
  const openTasks = snap.tasks.filter((t) => !["DONE", "CANCELLED"].includes(t.status)).length;
  const reviewTasks = snap.tasks.filter((t) => t.status === "REVIEW").length;
  const emptySections = SECTIONS.filter((s) => !(snap.artifact!.sections[s.id] ?? "").trim());
  const noticeUnread = Math.max(0, noticeMsgs.length - noticeSeen);
  const highlight = (body: string, quote: string | null) => {
    if (!quote) return body;
    const i = body.indexOf(quote);
    if (i < 0) return body;
    return <>{body.slice(0, i)}<mark>{body.slice(i, i + quote.length)}</mark>{body.slice(i + quote.length)}</>;
  };
  const showWork = (tab: "doc" | "tasks" | "assistant") => { setWorkTab(tab); setWorkOpen(true); setNavOpen(false); };
  const ch = CHANNELS[channel];
  const avatarSm = { width: 28, height: 28, fontSize: 12 };

  return (
    <div className="ws">
      <a href="#main-chat" className="skip-link">주요 콘텐츠로 이동</a>
      <a href="#composer" className="skip-link">메시지 입력으로 이동</a>
      <header className="topbar">
        <button className="btn btn-tertiary btn-icon btn-sm nav-toggle" aria-label="워크스페이스 메뉴" aria-expanded={navOpen} onClick={() => setNavOpen((v) => !v)}><Icon name="menu" /></button>
        <span className="wordmark"><span className="wordmark-dot" aria-hidden="true" />Day Zero</span>
        <span className="vdivider" aria-hidden="true" />
        <span className="project-name">{snap.brief.company_name} · {snap.brief.service_name} 재참여율 개선 프로젝트</span>
        <span className="spacer" />
        {conn === "reconnecting" && <span className="badge info" role="status"><span className="spin" aria-hidden="true" />연결 복구 중</span>}
        <span className="hide-md" aria-live="polite">
          {save.state === "saving" && <span className="row small"><span className="spin" aria-hidden="true" />{COPY.saving}</span>}
          {save.state === "saved" && <span className="row small" style={{ color: "#15803d" }}><Icon name="check" />{COPY.saved}{save.savedAt ? ` · ${save.savedAt}` : ""}</span>}
          {save.state === "failed" && <span className="row small" style={{ color: "var(--color-error)" }}><Icon name="error" />저장 실패</span>}
        </span>
        {!submitted && <span className={`badge num ${remaining <= 10 ? "warning" : ""}`} aria-label={`남은 시간 ${fmtClock(remaining)}`}><Icon name="clock" />{fmtClock(remaining)}</span>}
        <button className="btn btn-sm mobile-switch" onClick={() => showWork("doc")}>기획안</button>
        <button className="btn btn-sm" onClick={() => { setBriefRequired(false); setBriefOpen(true); }}>과제 안내</button>
        {submitted ? <span className="badge success"><Icon name="check" />제출 완료</span>
          : <button className="btn btn-primary btn-sm" onClick={() => setSubmitOpen(true)}>제출하기</button>}
      </header>

      <div className="ws-main">
        <nav className={`pane ws-nav ${navOpen ? "open" : ""}`} aria-label="워크스페이스">
          <div className="ws-nav-context">
            <div className="strong" style={{ color: "var(--color-heading)" }}>{snap.brief.company_name}</div>
            <div className="small">{snap.brief.service_name} 재참여율 개선 프로젝트</div>
            <div className="muted">프로덕트팀 · 기획자</div>
          </div>
          <div className="ws-nav-group">
            <div className="ws-nav-title">업무</div>
            <button className="nav-item" onClick={() => { setBriefRequired(false); setBriefOpen(true); }}><Icon name="brief" />과제 안내</button>
            <button className="nav-item" aria-current={workTab === "doc"} onClick={() => showWork("doc")}><Icon name="edit" />기획안
              {snap.approvals.length > 0 && <span className="count badge warning">승인 {snap.approvals.length}</span>}</button>
            <button className="nav-item" aria-current={workTab === "tasks"} onClick={() => showWork("tasks")}><Icon name="task" />태스크
              <span className={`count badge ${reviewTasks ? "warning" : ""}`} aria-label={`미완료 ${openTasks}개`}>{openTasks}</span></button>
          </div>
          <div className="ws-nav-group">
            <div className="ws-nav-title">채널</div>
            {(["notice", "team"] as Channel[]).map((c) => (
              <button key={c} className="nav-item" aria-current={channel === c} onClick={() => { setChannel(c); setNavOpen(false); }}>
                <Icon name="hash" />{CHANNELS[c].name}
                {c === "notice" && noticeUnread > 0 && channel !== "notice" && <span className="count badge info" aria-label={`새 공지 ${noticeUnread}개`}>{noticeUnread}</span>}
              </button>
            ))}
          </div>
          <div className="ws-nav-group">
            <div className="ws-nav-title">자료실</div>
            {docs.length === 0 && <p className="muted" style={{ padding: "0 8px" }}>자료를 불러오는 중…</p>}
            {docs.map((d) => (
              <button key={d.id} className="nav-item" disabled={d.available === false} onClick={() => openDocument(d.id)}
                aria-current={docView?.doc.id === d.id} title={d.available === false ? (d.notice ?? "아직 공유되지 않음") : d.title}>
                <Icon name={d.available === false ? "lock" : "doc"} />
                <span style={{ minWidth: 0 }}>{d.title}{d.available === false && <span className="muted" style={{ display: "block" }}>{d.notice ?? "아직 공유되지 않음"}</span>}</span>
              </button>
            ))}
          </div>
          <div className="ws-nav-foot">
            <button className="btn btn-block" aria-pressed={workTab === "assistant"} onClick={() => showWork("assistant")}><Icon name="sparkle" />AI 어시스턴트 열기</button>
          </div>
        </nav>

        <main className="pane messenger" id="main-chat" aria-label={`# ${ch.name} 채널`}>
          <div className="channel-head">
            <div style={{ minWidth: 0 }}>
              <h3 className="row"><Icon name="hash" />{ch.name}</h3>
              <p className="muted" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{ch.desc}</p>
            </div>
            <span className="spacer" />
            <span className="row" aria-label="참여자: 한서윤, 이도현, 나">
              <span className="avatar" aria-hidden="true" style={avatarSm}>한</span>
              <span className="avatar colleague" aria-hidden="true" style={avatarSm}>이</span>
              <span className="avatar me" aria-hidden="true" style={avatarSm}>나</span>
            </span>
            <button className="btn btn-sm hide-md" onClick={() => showWork("assistant")}><Icon name="sparkle" />AI 어시스턴트</button>
          </div>
          {snap.approvals.length > 0 && channel === "team" && (
            <div className="sys-row"><div><Icon name="warning" />{COPY.approval_title} · {snap.approvals.length}건
              <button className="btn btn-sm" onClick={() => showWork("doc")}>기획안에서 확인</button></div></div>
          )}
          <Messenger
            key={channel}
            messages={channel === "notice" ? noticeMsgs : team}
            run={channel === "team" ? runs.COLLEAGUE ?? null : null}
            canWrite={channel === "team" && !submitted}
            readOnlyNote={submitted ? "제출된 세션입니다. 메시지를 보낼 수 없습니다." : "공지 채널에는 입력할 수 없습니다. # 재참여-개선 채널을 이용해 주세요."}
            busy={busyFor("COLLEAGUE")}
            placeholder={COPY.composer}
            emptyText="프로젝트가 시작되었습니다. 팀장 안내를 확인하고, 필요한 자료를 읽거나 이도현 동료에게 말을 걸어 보세요."
            onSend={(t) => send("TEAM", t)} onRetry={retryRun}
            onOpenCitation={(c: Citation) => openDocument(c.document_id, c.quote)}
            split={{ activeMessageId: activeSplitMessageId, confirmed: !!snap.split?.confirmed, onDecide: decideSplit }}
          />
        </main>

        <aside className={`pane work ${workOpen ? "open" : ""}`} aria-label="작업 패널">
          <div className="work-head">
            <div className="work-title">
              <h3 style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{snap.brief.service_name} 재참여율 개선 신규 기능 기획안</h3>
              <span className="badge num">v{snap.artifact.version}</span>
              <span className="spacer" />
              <button className="btn btn-tertiary btn-icon btn-sm mobile-switch" aria-label="작업 패널 닫기" onClick={() => setWorkOpen(false)}><Icon name="close" /></button>
            </div>
            <div className="tabs" role="tablist" aria-label="작업 패널 탭">
              <button role="tab" id="tab-doc" aria-controls="panel-doc" className="tab" aria-selected={workTab === "doc"} onClick={() => setWorkTab("doc")}>
                기획안 {snap.approvals.length > 0 && <span className="badge warning">승인 {snap.approvals.length}</span>}</button>
              <button role="tab" id="tab-tasks" aria-controls="panel-tasks" className="tab" aria-selected={workTab === "tasks"} onClick={() => setWorkTab("tasks")}>
                태스크 <span className="badge" aria-label={`미완료 ${openTasks}개`}>{openTasks}</span></button>
              <button role="tab" id="tab-assistant" aria-controls="panel-assistant" className="tab" aria-selected={workTab === "assistant"} onClick={() => setWorkTab("assistant")}>
                <Icon name="sparkle" />AI 어시스턴트</button>
            </div>
          </div>
          <div className={`work-body ${workTab === "assistant" ? "assistant-body" : ""}`}>
            <div id="panel-doc" role="tabpanel" aria-labelledby="tab-doc" hidden={workTab !== "doc"}>
              {snap.approvals.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  {snap.approvals.map((a) => <ApprovalCard key={a.id} a={a} busy={busyApproval} onDecide={(d) => decide(a.id, d)} />)}
                </div>
              )}
              {submitted && <div className="alert success" style={{ marginBottom: 16 }}><Icon name="check" />{COPY.submitted}. 읽기 전용입니다.</div>}
              <ArtifactEditor sessionId={sid} artifact={snap.artifact} readOnly={submitted}
                onSaved={(a: Artifact) => setSnap((s) => (s ? { ...s, artifact: a } : s))}
                reloadArtifact={async () => (await refresh())?.artifact ?? null} onSaveState={setSave} />
            </div>
            <div id="panel-tasks" role="tabpanel" aria-labelledby="tab-tasks" hidden={workTab !== "tasks"}>
              <TaskBoard tasks={snap.tasks} readOnly={submitted} onMove={moveTask} onReview={review} onRevoke={revoke} />
            </div>
            {workTab === "assistant" && (
              <div id="panel-assistant" role="tabpanel" aria-labelledby="tab-assistant" className="messenger" style={{ flex: 1, minHeight: 0 }}>
                <div className="row" style={{ padding: "12px 20px 0" }}><span className="badge">읽기 전용</span><span className="help" style={{ marginTop: 0, flex: 1 }}>{COPY.assistant_desc}</span></div>
                <Messenger
                  messages={assistantMsgs} run={runs.ASSISTANT ?? null} canWrite={!submitted}
                  readOnlyNote="제출된 세션입니다." busy={busyFor("ASSISTANT")} composerId="assistant-composer"
                  placeholder="질문, 자료 요약, 비교 분석, 초안 작성을 요청하세요" emptyText="회사 자료를 근거로 답하고 참조 문서명을 알려 드립니다."
                  quickPrompts={["재참여율 정의 찾기", "운영 정책 요약하기", "지난주 회의록 요약하기"]}
                  onSend={(t) => send("ASSISTANT", t)} onRetry={retryRun}
                  onOpenCitation={(c: Citation) => openDocument(c.document_id, c.quote)}
                />
              </div>
            )}
          </div>
        </aside>
      </div>

      <Drawer open={!!docView} kind="side" modal={false} title={docView?.doc.title ?? ""} badge={<span className="badge num">v{docView?.doc.version}</span>} onClose={() => setDocView(null)}>
        {docView && (
          <div className="stack">
            <p className="muted">회사 자료 · 원문은 수정할 수 없습니다{docView.quote ? " · 인용 구간을 강조했습니다" : ""} · 열어 둔 채로 채팅·기획안·어시스턴트를 함께 쓸 수 있습니다</p>
            <div className="doc-body">{highlight(docView.doc.body ?? "", docView.quote)}</div>
          </div>
        )}
      </Drawer>

      <Modal open={briefOpen} size="lg" title={COPY.brief_title}
        onClose={briefRequired ? undefined : () => setBriefOpen(false)}
        footer={<button className="btn btn-primary" data-autofocus onClick={() => { try { localStorage.setItem(`dz-brief-${sid}`, "1"); } catch { /* ignore */ } setBriefOpen(false); setBriefRequired(false); }}>
          {briefRequired ? "업무 시작하기" : "닫기"}</button>}>
        <div className="stack-lg">
          <div className="msg" style={{ padding: 0 }}>
            <span className="avatar" aria-hidden="true">한</span>
            <div><div className="msg-head"><span className="msg-name">한서윤</span><span className="badge">팀장</span></div>
              <div className="msg-body">{snap.brief.public_brief}</div></div>
          </div>
          <div className="stack"><h4>최종 제출물 · 2~3쪽 기획안</h4><ol className="checklist">{SECTIONS.map((s) => <li key={s.id}>{s.title.replace(/^\d+\.\s*/, "")}</li>)}</ol>
            <p className="help">작성 순서와 업무 분담은 자유롭게 조정할 수 있습니다. 문서는 자동 저장됩니다.</p></div>
          <div className="stack"><h4>함께 일하는 방법</h4>
            <ul className="checklist">
              <li>자료실의 회사 자료를 읽을 수 있습니다. 일부 자료는 공유된 뒤에 열립니다.</li>
              <li>이도현 동료와 # 재참여-개선 채널에서 업무를 나누고 의견을 나눌 수 있습니다.</li>
              <li>AI 어시스턴트는 오른쪽 패널의 별도 탭으로, 자료 요약·비교·초안 작성을 돕고 문서를 직접 바꾸지 않습니다.</li>
              <li>문제 정의, 기능 선택, 최종 기획안은 직접 결정합니다.</li>
            </ul></div>
          <p className="help">업무 시간은 2시간이며, 시간이 끝나면 저장된 내용으로 자동 제출됩니다. 협업 행동과 AI 활용 기록이 관찰에 사용되며 최종 판단은 사람이 합니다.</p>
        </div>
      </Modal>

      {submitOpen && <SubmitDialog sid={sid} artifact={snap.artifact} empty={emptySections.map((s) => s.title)} save={save.state}
        onClose={() => setSubmitOpen(false)} onDone={() => router.push(`/debrief/${sid}`)} onError={(m) => { setToast(m); scheduleRefresh(); }} />}

      {toast && (
        <div role="alert" className="alert warning" style={{ position: "fixed", top: 64, right: 16, width: 360, maxWidth: "calc(100vw - 32px)", zIndex: 100, boxShadow: "var(--shadow-sm)" }}>
          <Icon name="warning" /><span style={{ flex: 1 }}>{toast}</span>
          <button className="btn btn-tertiary btn-icon btn-sm" aria-label="알림 닫기" onClick={() => setToast(null)}><Icon name="close" /></button>
        </div>
      )}
    </div>
  );
}

function SubmitDialog({ sid, artifact, empty, save, onClose, onDone, onError }: {
  sid: string; artifact: Artifact; empty: string[]; save: SaveState;
  onClose: () => void; onDone: () => void; onError: (m: string) => void;
}) {
  const [summary, setSummary] = useState("");
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const blocked = save === "failed" || save === "conflict";
  const waiting = save === "saving" || save === "dirty";
  async function submit() {
    setBusy(true);
    try {
      await api(`/sessions/${sid}/submit`, { method: "POST", json: { base_version: artifact.version, summary } });
      onDone();
    } catch (e) {
      onError(errText(e, "제출하지 못했습니다. 작성한 내용은 저장되어 있습니다."));
      setBusy(false);
      onClose();
    }
  }
  return (
    <Modal open title="기획안을 제출할까요?" onClose={busy ? undefined : onClose}
      footer={<><button className="btn" disabled={busy} onClick={onClose}>계속 작성</button>
        <button className="btn btn-primary" disabled={!agree || busy || blocked || waiting} onClick={submit}>{busy ? "제출 중…" : "최종 제출"}</button></>}>
      <div className="stack">
        <ul className="checklist" style={{ listStyle: "none", paddingLeft: 0 }}>
          {SECTIONS.map((s) => {
            const filled = !empty.includes(s.title);
            return <li key={s.id} className="row">{filled ? <Icon name="check" /> : <Icon name="warning" />}{s.title}<span className={`badge ${filled ? "success" : ""}`}>{filled ? "작성됨" : "비어 있음"}</span></li>;
          })}
        </ul>
        {empty.length > 0 && <div className="alert warning"><Icon name="warning" />{`비어 있는 섹션이 ${empty.length}개 있습니다. 불완전한 상태로도 제출할 수 있습니다.`}</div>}
        {waiting && <div className="alert"><span className="spin" />저장이 끝나면 제출할 수 있습니다.</div>}
        {blocked && <div className="alert error"><Icon name="error" />저장되지 않은 변경이 있습니다. 기획안에서 다시 저장하거나 충돌을 해결한 뒤 제출해 주세요.</div>}
        <div className="field">
          <label htmlFor="submit-summary">팀장님께 남길 한 줄 요약(선택)</label>
          <textarea id="submit-summary" className="textarea" style={{ minHeight: 64 }} maxLength={2000} value={summary} onChange={(e) => setSummary(e.target.value)} />
        </div>
        <label className="row" style={{ fontWeight: 400 }}><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />제출 후에는 문서와 진행 중 작업을 수정할 수 없음을 확인했습니다.</label>
      </div>
    </Modal>
  );
}
