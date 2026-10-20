"use client";
import { useState } from "react";
import { Icon } from "@/components/Icon";
import { COPY, fmtTime, type Approval } from "@/lib/types";

/** 승인 카드: 정정 요청 → 서윤 수정안 → 지원자 승인/거절. 승인해야만 산출물이 바뀐다(interrupt 후 재개). */
export function ApprovalCard({ a, busy, onDecide }: { a: Approval; busy: boolean; onDecide: (d: "APPROVE" | "REJECT") => void }) {
  const [full, setFull] = useState(false);
  const ba = a.before_after;
  return (
    <section className="approval stack" aria-label={COPY.approval_title}>
      <div className="row">
        <Icon name="warning" />
        <h3>{COPY.approval_title}</h3>
        <span className="spacer" />
        <span className="badge warning">승인 대기</span>
      </div>
      <dl className="kv">
        <dt>대상</dt><dd>{ba.artifact_key} {ba.title}</dd>
        <dt>제안자</dt><dd>한서윤 · AI 동료</dd>
        <dt>결정 기한</dt><dd className="num">{fmtTime(a.expires_at)}까지</dd>
      </dl>
      <div className="diff">
        <div><span className="small strong">지금</span><pre className={full ? "expanded" : ""}>{ba.before || "(비어 있음)"}</pre></div>
        <div><span className="small strong">서윤 님 수정안</span><pre className={full ? "expanded" : ""}>{ba.after}</pre></div>
      </div>
      <div className="row">
        <button className="btn btn-primary" disabled={busy} onClick={() => onDecide("APPROVE")}>승인하고 반영</button>
        <button className="btn btn-tertiary" disabled={busy} onClick={() => onDecide("REJECT")}>거절</button>
        <span className="spacer" />
        <button className="btn btn-tertiary btn-sm" onClick={() => setFull((v) => !v)} aria-expanded={full}>{full ? "접기" : "전체 보기"}</button>
      </div>
    </section>
  );
}
