"use client";
import { useState } from "react";
import { Icon } from "@/components/Icon";
import { COPY, fmtTime, SECTIONS, type Approval } from "@/lib/types";

/** 승인 카드 (DESIGN_GUIDE §4.6): 대상·제안자·이전/이후·범위·만료, 승인만 주요 행동. */
export function ApprovalCard({ a, busy, onDecide }: { a: Approval; busy: boolean; onDecide: (d: "APPROVE" | "REJECT") => void }) {
  const [full, setFull] = useState(false);
  const isDoc = a.tool_name === "patch_artifact_section";
  const section = SECTIONS.find((x) => x.id === a.before_after.section);
  return (
    <section className="approval stack" aria-label={COPY.approval_title}>
      <div className="row">
        <Icon name="warning" />
        <h3>{isDoc ? COPY.approval_title : "태스크 상태 변경 승인이 필요합니다"}</h3>
        <span className="spacer" />
        <span className="badge warning">승인 대기</span>
      </div>
      <dl className="kv">
        <dt>대상</dt><dd>{section?.title ?? "태스크"}</dd>
        <dt>제안자</dt><dd>이도현 · AI 동료</dd>
        <dt>범위</dt><dd>{section ? `${section.title} 섹션만` : "해당 태스크만"}</dd>
        <dt>결정 기한</dt><dd className="num">{fmtTime(a.expires_at)}까지</dd>
      </dl>
      <div className="diff">
        <div><span className="small strong">변경 전</span><pre className={full ? "expanded" : ""}>{a.before_after.before || "(비어 있음)"}</pre></div>
        <div><span className="small strong">변경 후 · 추가됨</span><pre className={full ? "expanded" : ""}>{a.before_after.after}</pre></div>
      </div>
      <div className="row">
        <button className="btn btn-primary" disabled={busy} onClick={() => onDecide("APPROVE")}>승인하고 반영</button>
        <button className="btn" disabled={busy} onClick={() => onDecide("REJECT")}>거절</button>
        <span className="spacer" />
        <button className="btn btn-tertiary btn-sm" onClick={() => setFull((v) => !v)} aria-expanded={full}>{full ? "접기" : "전체 보기"}</button>
      </div>
    </section>
  );
}
