"use client";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApprovalCard } from "@/components/ApprovalCard";
import { ArtifactEditor } from "@/components/ArtifactEditor";
import { Icon } from "@/components/Icon";
import { Messenger, type RunView } from "@/components/Messenger";
import { Drawer, Modal } from "@/components/Overlay";
import { TaskBoard } from "@/components/TaskBoard";
import { api, ApiError, loadMe, uuid } from "@/lib/api";
import { subscribe, type StreamEvent } from "@/lib/events";
import { COPY, DOC_TITLE, ERROR_COPY, type Artifact, type Citation, type Snapshot, type SplitProposal, type Task } from "@/lib/types";

type Doc = { id: string; title: string; version: number; body?: string; live?: boolean };

function errText(e: unknown, fallback: string) {
  return e instanceof ApiError ? (ERROR_COPY[e.code] ?? e.message) : fallback;
}

/** 지원자 작업 공간: 좌측 공유 문서 4개 + 태스크 보드, 중앙 팀 메신저(서윤·팀장), 우측 내 산출물. 상단은 가상 시각. */
export default function Office() {
  const { sid } = useParams<{ sid: string }>();
  const router = useRouter();
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [docView, setDocView] = useState<{ doc: Doc; quote: string | null } | null>(null);
  const [leftTab, setLeftTab] = useState<"docs" | "tasks">("docs");
  const [briefOpen, setBriefOpen] = useState(false);
  const [briefRequired, setBriefRequired] = useState(false);
  const [endOpen, setEndOpen] = useState(false);
  const [workOpen, setWorkOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [run, setRun] = useState<RunView>(null);
  const [recipient, setRecipient] = useState<"COLLEAGUE" | "MANAGER">("COLLEAGUE");
  const [conn, setConn] = useState<"open" | "reconnecting">("open");
  const [toast, setToast] = useState<string | null>(null);
  const [busyApproval, setBusyApproval] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closed = useRef(false); // 종료 후에는 재조회하지 않는다(지원자 재열람 차단 403)

  const refresh = useCallback(async () => {
    try {
      const s = await api<Snapshot>(`/sessions/${sid}`);
      setSnap(s);
      if (s.session.status === "CREATED") router.replace("/join");
      return s;
    } catch (e) {
      if (e instanceof ApiError && e.code === "SESSION_CLOSED") { router.replace(`/debrief/${sid}`); return null; }
      setFatal(e instanceof ApiError && (e.status === 401 || e.status === 404)
        ? "이 작업 공간에 접근할 수 없습니다. 초대 링크로 다시 입장해 주세요." : "작업 공간을 불러오지 못했습니다. 새로고침해 주세요.");
      return null;
    }
  }, [sid, router]);
  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) clearTimeout(refreshTimer.current);
    if (closed.current) return;
    refreshTimer.current = setTimeout(refresh, 150);
  }, [refresh]);

  useEffect(() => {
    document.documentElement.classList.add("exam-fullscreen");
    return () => document.documentElement.classList.remove("exam-fullscreen");
  }, []);
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
      api<{ items: Doc[] }>(`/sessions/${sid}/documents`).then((r) => setDocs(r.items)).catch(() => undefined);
      unsub = subscribe(sid, s.session.last_stream_seq, (e: StreamEvent) => {
        if (e.type === "RUN_STARTED") setRun({ state: "running", text: "답장을 쓰고 있어요." });
        else if (e.type === "COLLEAGUE_MESSAGE" || e.type === "MANAGER_MESSAGE" || e.type === "SYSTEM_NOTICE" || e.type === "DONE"
          || e.type === "APPROVAL_REQUIRED") setRun(null);
        else if (e.type === "FAILED") setRun({ state: "failed", text: COPY.ai_failed, runId: e.run_id });
        else if (e.type === "SESSION_DONE") { closed.current = true; router.push(`/debrief/${sid}`); return; }
        if (e.type === "APPROVAL_REQUIRED") setWorkOpen(true);
        scheduleRefresh();
      }, setConn);
    })();
    return () => unsub?.();
  }, [sid, refresh, scheduleRefresh, router]);

  async function openDocument(id: string, quote: string | null = null) {
    try {
      const d = await api<Doc>(`/sessions/${sid}/documents/${id}`);
      setDocView({ doc: d, quote });
      setNavOpen(false);
    } catch (e) { setToast(errText(e, "문서를 열지 못했습니다")); }
  }
  async function send(content: string) {
    try {
      await api(`/sessions/${sid}/messages`, { method: "POST", json: { client_message_id: uuid(), channel: "TEAM", content, to: recipient } });
      setRun({ state: "running", text: "메시지를 전달했어요." });
      scheduleRefresh();
      return true;
    } catch (e) { setToast(errText(e, "메시지를 보내지 못했습니다. 입력한 내용은 그대로 남아 있습니다.")); return false; }
  }
  async function propose(p: SplitProposal) {
    try { await api(`/sessions/${sid}/split`, { method: "POST", json: { proposal: p } }); setRun({ state: "running", text: "분업안을 전달했어요." }); scheduleRefresh(); }
    catch (e) { setToast(errText(e, "분업안을 보내지 못했습니다")); }
  }
  async function decide(aid: string, decision: "APPROVE" | "REJECT") {
    setBusyApproval(true);
    try { await api(`/sessions/${sid}/approvals/${aid}/decision`, { method: "POST", json: { decision } }); }
    catch (e) { setToast(errText(e, "결정을 저장하지 못했습니다")); }
    finally { setBusyApproval(false); scheduleRefresh(); }
  }
  async function patchTask(t: Task, p: { status?: string; owner?: string; eta?: string }) {
    try { await api(`/sessions/${sid}/tasks/${t.key}`, { method: "PATCH", json: { base_version: t.version, ...p } }); }
    catch (e) { setToast(errText(e, "태스크를 변경하지 못했습니다")); }
    finally { scheduleRefresh(); }
  }
  async function retryRun(rid: string) {
    try { await api(`/runs/${rid}/retry`, { method: "POST", json: {} }); setRun(null); }
    catch (e) { setToast(errText(e, "재시도하지 못했습니다")); }
  }

  if (fatal && !snap) return <main className="center-wrap"><div className="card center-card"><div className="alert error" role="alert"><Icon name="error" />{fatal}</div></div></main>;
  if (!snap) return <main className="center-wrap"><p className="row muted"><span className="spin" />작업 공간을 여는 중…</p></main>;
  const ended = snap.session.status === "SUBMITTED";
  const busy = !!snap.active_run;
  const splitMsg = snap.messages.find((m) => m.meta?.split_proposal);
  const highlight = (body: string, quote: string | null) => {
    if (!quote) return body;
    const i = body.indexOf(quote);
    if (i < 0) return body;
    return <>{body.slice(0, i)}<mark>{body.slice(i, i + quote.length)}</mark>{body.slice(i + quote.length)}</>;
  };
  const avatarSm = { width: 28, height: 28, fontSize: 12 };

  return (
    <div className="ws">
      <a href="#main-chat" className="skip-link">주요 콘텐츠로 이동</a>
      <a href="#composer" className="skip-link">메시지 입력으로 이동</a>
      <header className="topbar">
        <button className="btn btn-tertiary btn-icon btn-sm nav-toggle" aria-label="문서·보드 열기" aria-expanded={navOpen} onClick={() => setNavOpen((v) => !v)}><Icon name="menu" /></button>
        <span className="wordmark"><span className="wordmark-dot" aria-hidden="true" />Day Zero</span>
        <span className="vdivider" aria-hidden="true" />
        <span className="project-name">{snap.brief.title}</span>
        <span className="spacer" />
        {conn === "reconnecting" && <span className="badge info" role="status"><span className="spin" aria-hidden="true" />연결 복구 중</span>}
        <span className="badge num" aria-label={`가상 시각 ${snap.clock.virtual_time}, 마감 ${snap.clock.deadline}`}>
          <Icon name="clock" />{snap.clock.virtual_time} · 마감 {snap.clock.deadline}</span>
        <button className="btn btn-sm mobile-switch" onClick={() => setWorkOpen(true)}>내 산출물{snap.approvals.length > 0 && ` · 승인 ${snap.approvals.length}`}</button>
        <button className="btn btn-sm" onClick={() => { setBriefRequired(false); setBriefOpen(true); }}>과제 안내</button>
        {ended ? <span className="badge success"><Icon name="check" />종료</span>
          : <button className="btn btn-primary btn-sm" onClick={() => setEndOpen(true)}>업무 종료</button>}
      </header>

      <div className="ws-main office">
        <nav className={`pane ws-nav ${navOpen ? "open" : ""}`} aria-label="공유 문서와 태스크 보드">
          <div className="ws-nav-context">
            <div className="strong" style={{ color: "var(--color-heading)" }}>{snap.brief.company}</div>
            <div className="small">{snap.brief.task_summary}</div>
          </div>
          <div style={{ padding: "8px 12px 0" }}>
            <div className="tabs" role="tablist" aria-label="왼쪽 패널">
              <button role="tab" className="tab" aria-selected={leftTab === "docs"} onClick={() => setLeftTab("docs")}><Icon name="doc" />공유 문서</button>
              <button role="tab" className="tab" aria-selected={leftTab === "tasks"} onClick={() => setLeftTab("tasks")}><Icon name="task" />태스크 보드</button>
            </div>
          </div>
          <div style={{ padding: 12, overflow: "auto", flex: 1, minHeight: 0 }}>
            {leftTab === "docs" ? (
              <div>
                {docs.length === 0 && <p className="muted">문서를 불러오는 중…</p>}
                {docs.map((d) => (
                  <button key={d.id} className="nav-item" onClick={() => openDocument(d.id)} aria-current={docView?.doc.id === d.id}>
                    <Icon name="doc" /><span style={{ minWidth: 0 }}>{DOC_TITLE[d.id] ?? d.title}
                      {d.live && <span className="muted" style={{ display: "block" }}>함께 쓰는 작업본</span>}</span>
                  </button>
                ))}
              </div>
            ) : <TaskBoard tasks={snap.tasks} readOnly={ended} onPatch={patchTask} />}
          </div>
        </nav>

        <main className="pane messenger" id="main-chat" aria-label="팀 메신저">
          <div className="channel-head">
            <div style={{ minWidth: 0 }}>
              <h3 className="row"><Icon name="hash" />운영팀</h3>
              <p className="muted">한서윤(AI 동료)·박준호 팀장과 함께 쓰는 채널입니다.{snap.colleague.offline ? " 서윤 님은 지금 자리 비움입니다." : ""}</p>
            </div>
            <span className="row" aria-label="참여자: 박준호 팀장, 한서윤, 나">
              <span className="avatar" aria-hidden="true" style={avatarSm}>박</span>
              <span className="avatar colleague" aria-hidden="true" style={{ ...avatarSm, opacity: snap.colleague.offline ? 0.4 : 1 }}>한</span>
              <span className="avatar me" aria-hidden="true" style={avatarSm}>나</span>
            </span>
          </div>
          {snap.approvals.length > 0 && (
            <div className="sys-row"><div><Icon name="warning" />{COPY.approval_title} · {snap.approvals.length}건
              <button className="btn btn-sm" onClick={() => setWorkOpen(true)}>확인하기</button></div></div>
          )}
          <Messenger
            messages={snap.messages}
            run={snap.approvals.length ? null : run}
            canWrite={!ended}
            readOnlyNote="종료된 세션입니다. 메시지를 보낼 수 없습니다."
            busy={busy}
            placeholder={recipient === "MANAGER" ? "박준호 팀장님께 메시지" : "한서윤 님께 메시지"}
            emptyText="곧 팀장님이 오늘 업무를 공지합니다."
            recipient={recipient} onRecipient={setRecipient}
            onSend={send} onRetry={retryRun}
            onOpenCitation={(c: Citation) => openDocument(c.document_id, c.quote)}
            split={snap.split && splitMsg ? { proposal: snap.split.proposal, confirmed: snap.split.confirmed, rounds: snap.split.rounds,
              maxRounds: snap.split.max_rounds, onPropose: propose } : undefined}
          />
        </main>

        <aside className={`pane work ${workOpen ? "open" : ""}`} aria-label="내 산출물">
          <div className="work-head">
            <div className="work-title">
              <h3>내 산출물</h3>
              <span className="spacer" />
              <button className="btn btn-tertiary btn-icon btn-sm mobile-switch" aria-label="닫기" onClick={() => setWorkOpen(false)}><Icon name="close" /></button>
            </div>
          </div>
          <div className="work-body">
            {snap.approvals.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                {snap.approvals.map((a) => <ApprovalCard key={a.id} a={a} busy={busyApproval} onDecide={(d) => decide(a.id, d)} />)}
              </div>
            )}
            {ended && <div className="alert success" style={{ marginBottom: 16 }}><Icon name="check" />업무가 종료되었습니다. 읽기 전용입니다.</div>}
            <ArtifactEditor sessionId={sid} artifacts={snap.artifacts} readOnly={ended}
              onSaved={(a: Artifact) => { setSnap((s) => (s ? { ...s, artifacts: s.artifacts.map((x) => (x.key === a.key ? a : x)) } : s)); scheduleRefresh(); }} />
          </div>
        </aside>
      </div>

      <Drawer open={!!docView} kind="side" modal={false} title={docView ? (DOC_TITLE[docView.doc.id] ?? docView.doc.title) : ""}
        badge={<span className="badge num">v{docView?.doc.version}</span>} onClose={() => setDocView(null)}>
        {docView && (
          <div className="stack">
            <p className="muted">{docView.doc.live ? "함께 쓰는 작업본입니다. 고칠 내용은 오른쪽 '내 산출물'에서 저장하거나 서윤 님에게 요청하세요." : "공유 문서 · 읽기 전용"}</p>
            <div className="doc-body">{highlight(docView.doc.body ?? "", docView.quote)}</div>
          </div>
        )}
      </Drawer>

      <Modal open={briefOpen} size="lg" title={COPY.brief_title}
        onClose={briefRequired ? undefined : () => setBriefOpen(false)}
        footer={<button className="btn btn-primary" data-autofocus onClick={() => { try { localStorage.setItem(`dz-brief-${sid}`, "1"); } catch { /* ignore */ } setBriefOpen(false); setBriefRequired(false); }}>
          {briefRequired ? "업무 시작하기" : "닫기"}</button>}>
        <div className="stack-lg">
          <p>{snap.brief.company} 운영팀 신입으로, 동료 한서윤 님과 함께 {snap.brief.task_summary}</p>
          <div className="stack"><h4>함께 일하는 사람</h4>
            <ul className="checklist">
              <li>박준호 팀장 — 운영팀장. 업무 지시와 변경 사항을 알려 줍니다.</li>
              <li>한서윤 — 운영팀 1년차 AI 동료. 메신저로 대화하고, 수정을 부탁하면 수정안을 보내 확인을 받습니다.</li>
            </ul></div>
          <div className="stack"><h4>화면 안내</h4>
            <ul className="checklist">
              <li>왼쪽: 공유 문서 4개(브리프, 리워드·일정 표, FAQ 초안, 톤 가이드)와 태스크 보드(담당·상태·예상 완료 시각)</li>
              <li>가운데: 팀 메신저. 받는 사람을 골라 서윤 님이나 팀장님께 보낼 수 있습니다.</li>
              <li>오른쪽: 내 산출물. 수정한 뒤 &apos;저장&apos;을 눌러야 저장됩니다.</li>
            </ul></div>
          <p className="help">이 시뮬레이션은 협업 상황에서 일하는 방식을 봅니다. 결과물 완성도는 평가하지 않습니다.
            상단 시각({snap.clock.start}~{snap.clock.deadline})은 가상 시각이며 진행에 따라 바뀝니다. 대화와 작업 기록이 관찰에 사용되며 최종 판단은 사람이 합니다.</p>
        </div>
      </Modal>

      {endOpen && <EndDialog sid={sid} onClose={() => setEndOpen(false)} onDone={() => { closed.current = true; router.push(`/debrief/${sid}`); }}
        onError={(m) => { setToast(m); scheduleRefresh(); }} />}

      {toast && (
        <div role="alert" className="alert warning" style={{ position: "fixed", top: 64, right: 16, width: 360, maxWidth: "calc(100vw - 32px)", zIndex: 100, boxShadow: "var(--shadow-sm)" }}>
          <Icon name="warning" /><span style={{ flex: 1 }}>{toast}</span>
          <button className="btn btn-tertiary btn-icon btn-sm" aria-label="알림 닫기" onClick={() => setToast(null)}><Icon name="close" /></button>
        </div>
      )}
    </div>
  );
}

function EndDialog({ sid, onClose, onDone, onError }: { sid: string; onClose: () => void; onDone: () => void; onError: (m: string) => void }) {
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  async function end() {
    setBusy(true);
    try {
      await api(`/sessions/${sid}/submit`, { method: "POST", json: { summary: "" } });
      onDone();
    } catch (e) {
      onError(errText(e, "업무를 종료하지 못했습니다. 작성한 내용은 저장되어 있습니다."));
      setBusy(false);
      onClose();
    }
  }
  return (
    <Modal open title="오늘 업무를 종료할까요?" onClose={busy ? undefined : onClose}
      footer={<><button className="btn" disabled={busy} onClick={onClose}>계속 일하기</button>
        <button className="btn btn-primary" disabled={!agree || busy} onClick={end}>{busy ? "종료 중…" : "업무 종료"}</button></>}>
      <div className="stack">
        <p>저장하지 않은 산출물 변경은 반영되지 않습니다. 미완료 태스크가 있어도 종료할 수 있습니다.</p>
        <label className="row" style={{ fontWeight: 400 }}><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />{COPY.submit_confirm}</label>
      </div>
    </Modal>
  );
}
