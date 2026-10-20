"use client";
import { useEffect, useRef, useState } from "react";
import { SplitCard } from "@/components/SplitCard";
import { ACTOR_LABEL, type Citation, type Message, type Owner } from "@/lib/types";

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
  activeSplitMessageId: string | null;
  splitConfirmed: boolean;
  onSplit: (decision: "ACCEPT" | "ADJUST", assignments: Record<string, Owner>) => Promise<void>;
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
              ? "팀 채팅입니다. 팀장 한서윤, 동료 이도현과 대화할 수 있습니다."
              : "AI 어시스턴트에게 질문, 자료 요약, 비교 분석, 초안 작성을 요청할 수 있습니다. 어시스턴트는 공유 문서를 직접 수정하지 않습니다."}
          </p>
        )}
        {list.map((m) => {
          const cls = m.actor === "CANDIDATE" ? "me" : m.actor === "MANAGER" ? "manager" : m.actor === "SYSTEM" ? "system" : "";
          const prop = m.meta?.split_proposal;
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
                      {c.document_id === "rejoin_facts" ? (
                        <span title={c.quote}>지표 조회(rejoin-data-v1)</span>
                      ) : (
                        <button type="button" onClick={() => p.onOpenCitation(c)} title={c.quote}>{c.document_id}{c.chunk_id ? ` #${c.chunk_id.split(":").pop()}` : ""}</button>
                      )}
                    </span>
                  ))}
                </div>
              )}
              {prop && (
                <SplitCard proposal={prop} active={!p.disabled && !p.splitConfirmed && p.activeSplitMessageId === m.id}
                  confirmed={p.splitConfirmed && p.activeSplitMessageId === m.id} onDecide={p.onSplit} />
              )}
            </div>
          );
        })}
      </div>
      {p.progress && <div className="progress" role="status">{p.progress}</div>}
      {p.failedRunId && (
        <div className="progress row" role="alert">
          <span className="badge error">응답 실패</span> 입력과 작업은 저장되어 있습니다.
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
          placeholder={p.channel === "TEAM" ? "팀 채팅에 메시지 입력 (Enter 전송, Shift+Enter 줄바꿈)" : "AI 어시스턴트에게 요청하기"}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}
        />
        <button className="btn btn-primary" disabled={p.busy || p.disabled || !text.trim()}>보내기</button>
      </form>
    </div>
  );
}
