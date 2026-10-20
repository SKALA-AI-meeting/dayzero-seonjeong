"use client";
import { useEffect, useRef, useState } from "react";
import { ACTOR_LABEL, type Citation, type DelegationProposal, type Message } from "@/lib/types";

type Props = {
  channel: "TEAM" | "ASSISTANT";
  messages: Message[];
  progress: string | null;
  busy: boolean;
  disabled: boolean;
  failedRunId: string | null;
  onSend: (text: string) => Promise<boolean>;
  onRetry: (runId: string) => void;
  onOpenCitation: (c: Citation) => void;
  onConfirmDelegation: (p: DelegationProposal) => void;
  confirmedProposals: Set<string>;
};

export function Chat(p: Props) {
  const [text, setText] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const list = p.messages.filter((m) => m.channel === p.channel);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [list.length, p.progress]);

  async function send(e?: React.FormEvent) {
    e?.preventDefault();
    const t = text.trim();
    if (!t || p.busy || p.disabled) return;
    const ok = await p.onSend(t);
    if (ok) setText(""); // 실패 시 입력 보존
  }

  return (
    <div className="chat">
      <div className="chat-list" ref={listRef} aria-live="polite">
        {list.length === 0 && (
          <p className="muted">
            {p.channel === "TEAM"
              ? "팀 채팅입니다. 동료 이도현에게 조사를 요청하거나 위임할 수 있습니다."
              : "어시스턴트는 자료 조회만 돕는 별도 도구입니다. 기획안을 변경할 수 없습니다."}
          </p>
        )}
        {list.map((m) => {
          const cls = m.actor === "CANDIDATE" ? "me" : m.actor === "MANAGER" ? "manager" : "";
          const prop = m.meta?.delegation_proposal;
          return (
            <div key={m.id} className={`msg ${cls}`} id={`msg-${m.id}`}>
              <div className="who">{ACTOR_LABEL[m.actor] ?? m.actor} · {new Date(m.created_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}</div>
              <div className="bubble">{m.content}</div>
              {m.citations?.length > 0 && (
                <div className="cite">
                  출처:{" "}
                  {m.citations.map((c, i) => (
                    <span key={i}>
                      {i > 0 && ", "}
                      {c.document_id === "funnel_facts" ? (
                        <span title={c.quote}>지표 조회(cart-data-v1)</span>
                      ) : (
                        <button type="button" onClick={() => p.onOpenCitation(c)} title={c.quote}>{c.document_id}{c.chunk_id ? ` #${c.chunk_id.split(":").pop()}` : ""}</button>
                      )}
                    </span>
                  ))}
                </div>
              )}
              {prop && (
                <div className="card stack" style={{ marginTop: 8 }}>
                  <h4>위임 제안: {prop.title}</h4>
                  <div className="muted">대상 섹션: evidence(수치·출처·한계)만 · 허용 도구: {prop.allowed_tools.join(", ")}</div>
                  {Object.keys(prop.filters).length > 0 && <div className="muted">조사 범위: {Object.entries(prop.filters).map(([k, v]) => `${k}=${v}`).join(", ")}</div>}
                  <div className="muted">확인하면 동료 태스크와 위임이 생성됩니다. 문서 변경은 매번 승인 카드에서 따로 결정합니다.</div>
                  <div className="row">
                    {p.confirmedProposals.has(m.id)
                      ? <span className="badge success">위임 생성됨</span>
                      : <button className="btn btn-primary btn-sm" disabled={p.disabled} onClick={() => p.onConfirmDelegation(prop)}>이 범위로 위임</button>}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      {p.progress && <div className="progress" role="status">{p.progress}</div>}
      {p.failedRunId && (
        <div className="progress row" role="alert">
          <span className="badge error">동료 응답 실패</span> 입력과 작업은 저장되어 있습니다.
          <button className="btn btn-sm" onClick={() => p.onRetry(p.failedRunId!)}>다시 시도</button>
        </div>
      )}
      <form className="composer" onSubmit={send}>
        <label htmlFor={`composer-${p.channel}`} className="sr-only" style={{ position: "absolute", left: -9999 }}>메시지</label>
        <textarea
          id={`composer-${p.channel}`}
          className="textarea"
          value={text}
          disabled={p.disabled}
          placeholder={p.channel === "TEAM" ? "예: current 기간 모바일 신규 고객 지표를 조사해 주세요" : "어시스턴트에게 자료 조회를 요청하세요"}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}
        />
        <button className="btn btn-primary" disabled={p.busy || p.disabled || !text.trim()}>보내기</button>
      </form>
    </div>
  );
}
