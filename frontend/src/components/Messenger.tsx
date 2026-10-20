"use client";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { SplitCard } from "@/components/SplitCard";
import { ACTOR, DOC_TITLE, fmtTime, type Citation, type Message, type SplitProposal } from "@/lib/types";

export type RunView = { state: "running" | "failed"; text: string; runId?: string | null } | null;

type Props = {
  messages: Message[];
  run: RunView;
  canWrite: boolean;           // 채널 입력 가능 여부(공지 채널·제출 후 false)
  readOnlyNote?: string;
  busy: boolean;               // 같은 채널 run 진행 중
  placeholder: string;
  emptyText: string;
  composerId?: string;
  quickPrompts?: string[];
  onSend: (text: string) => Promise<boolean>;
  onRetry: (runId: string) => void;
  onOpenCitation: (c: Citation) => void;
  split?: { proposal: SplitProposal; confirmed: boolean; rounds: number; maxRounds: number; onPropose: (p: SplitProposal) => Promise<void> };
  recipient: "COLLEAGUE" | "MANAGER";
  onRecipient: (r: "COLLEAGUE" | "MANAGER") => void;
};

function citationLabel(c: Citation): string {
  return DOC_TITLE[c.document_id] ?? c.document_id;
}

/** 채팅 본문 최소 마크다운: **굵게**만 렌더링하고 제목 기호(#)는 제거. HTML은 해석하지 않는다. */
function RichText({ text }: { text: string }) {
  const clean = text.replace(/^#{1,6}\s+/gm, "");
  const parts = clean.split(/(\*\*[^*\n]+\*\*)/g);
  return <>{parts.map((s, i) => (s.startsWith("**") && s.endsWith("**") && s.length > 4 ? <strong key={i}>{s.slice(2, -2)}</strong> : s))}</>;
}

export function Messenger(p: Props) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [unseen, setUnseen] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const atBottom = useRef(true);
  const prevLen = useRef(p.messages.length);

  // 하단에 있을 때만 자동 스크롤, 위를 읽는 중이면 "새 메시지 N개" (§9.4)
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const added = p.messages.length - prevLen.current;
    prevLen.current = p.messages.length;
    if (atBottom.current) el.scrollTop = el.scrollHeight;
    else if (added > 0) setUnseen((n) => n + added);
  }, [p.messages.length, p.run?.text]);

  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(144, ta.scrollHeight)}px`;
  }, [text]);

  function onScroll() {
    const el = listRef.current;
    if (!el) return;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (atBottom.current) setUnseen(0);
  }

  async function send(value = text) {
    const t = value.trim();
    if (!t || p.busy || !p.canWrite || sending) return;
    setSending(true);
    const ok = await p.onSend(t);
    setSending(false);
    if (ok) { setText(""); atBottom.current = true; } // 실패 시 입력 보존
  }

  return (
    <>
      <div className="msg-list" ref={listRef} onScroll={onScroll} aria-label="메시지 목록">
        <div className="msg-list-inner">
          {p.messages.length === 0 && (
            <div className="sys-row"><div><Icon name="info" />{p.emptyText}</div></div>
          )}
          {p.messages.map((m) => {
            if (m.actor === "SYSTEM") {
              return <div key={m.id} className="sys-row" id={`msg-${m.id}`}><div><Icon name="info" />{m.content}<span className="muted">· {fmtTime(m.created_at)}</span></div></div>;
            }
            const a = ACTOR[m.actor] ?? ACTOR.SYSTEM;
            const prop = m.meta?.split_proposal;
            return (
              <div key={m.id} className={`msg ${m.actor === "CANDIDATE" ? "me" : ""}`} id={`msg-${m.id}`}>
                <span className={`avatar ${a.avatar}`} aria-hidden="true">{a.initial}</span>
                <div style={{ minWidth: 0 }}>
                  <div className="msg-head">
                    <span className="msg-name">{a.name}</span>
                    {a.badge && <span className={`badge ${a.badge[1]}`}>{a.badge[0]}</span>}
                    {m.actor === "CANDIDATE" && m.meta?.to === "MANAGER" && <span className="badge">→ 박준호 팀장</span>}
                    <span className="muted num">{fmtTime(m.created_at)}</span>
                  </div>
                  <div className="msg-body"><RichText text={m.content} /></div>
                  {m.citations?.length > 0 && (
                    <div className="chips" aria-label="출처">
                      {m.citations.map((c, i) => (
                        <button key={i} type="button" className="chip" title={c.quote} onClick={() => p.onOpenCitation(c)}><Icon name="doc" />{citationLabel(c)}</button>))}
                    </div>
                  )}
                  {prop && p.split && (
                    <div className="inline-card">
                      <SplitCard proposal={p.split.proposal} active={p.canWrite && !p.split.confirmed && !p.busy}
                        confirmed={p.split.confirmed} rounds={p.split.rounds} maxRounds={p.split.maxRounds} onPropose={p.split.onPropose} />
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          {p.run && (
            <div className={`run-card ${p.run.state === "failed" ? "failed" : ""}`} role="status" aria-live="polite">
              {p.run.state === "running" ? <span className="spin" aria-hidden="true" /> : <Icon name="warning" />}
              <span>{p.run.text}</span>
              {p.run.state === "failed" && p.run.runId && <button className="btn btn-sm" onClick={() => p.onRetry(p.run!.runId!)}>다시 시도</button>}
            </div>
          )}
        </div>
        {unseen > 0 && (
          <div className="new-msg"><button className="btn btn-sm" onClick={() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight }); setUnseen(0); }}>새 메시지 {unseen}개</button></div>
        )}
      </div>
      <div className="composer">
        {p.canWrite ? (
          <>
            {p.quickPrompts && p.messages.length === 0 && (
              <div className="chips" style={{ marginTop: 0, marginBottom: 8 }}>
                {p.quickPrompts.map((q) => <button key={q} className="chip" onClick={() => send(q)}>{q}</button>)}
              </div>
            )}
            <div className="row" style={{ marginBottom: 8 }} role="radiogroup" aria-label="받는 사람">
              <span className="small muted">받는 사람</span>
              {(["COLLEAGUE", "MANAGER"] as const).map((r) => (
                <button key={r} type="button" role="radio" aria-checked={p.recipient === r}
                  className={`btn btn-sm ${p.recipient === r ? "btn-primary" : ""}`} onClick={() => p.onRecipient(r)}>
                  {r === "COLLEAGUE" ? "한서윤 (AI 동료)" : "박준호 팀장"}</button>
              ))}
            </div>
            <div className="composer-box">
              <label htmlFor={p.composerId ?? "composer"} className="sr-only">메시지</label>
              <textarea id={p.composerId ?? "composer"} ref={taRef} rows={1} value={text} placeholder={p.placeholder} aria-describedby={`${p.composerId ?? "composer"}-help`}
                onChange={(e) => setText(e.target.value)} maxLength={4000}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }} />
              <button className="btn btn-primary btn-icon" aria-label="메시지 보내기" disabled={p.busy || sending || !text.trim()} onClick={() => send()}>
                <Icon name="send" />
              </button>
            </div>
            <p id={`${p.composerId ?? "composer"}-help`} className="help">{p.busy ? "답변이 끝나면 다음 메시지를 보낼 수 있습니다." : "Enter 전송 · Shift+Enter 줄바꿈"}</p>
          </>
        ) : <p className="help"><Icon name="lock" /> {p.readOnlyNote}</p>}
      </div>
    </>
  );
}
