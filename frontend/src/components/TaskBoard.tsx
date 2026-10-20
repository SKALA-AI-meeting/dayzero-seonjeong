"use client";
import { useState } from "react";
import { Icon } from "@/components/Icon";
import { ACTOR, OWNER_LABEL, SECTIONS, TASK_STATUS, type Task } from "@/lib/types";

const COLS = ["REVIEW", "IN_PROGRESS", "TODO", "DONE"] as const;

/** 태스크 보드 (DESIGN_GUIDE §4.7, §6.9): 드래그 없이 상태별 목록 + 버튼 전이. */
export function TaskBoard({ tasks, readOnly, workingTaskIds, onMove, onReview, onRevoke }: {
  tasks: Task[]; readOnly: boolean; workingTaskIds: Set<string>;
  onMove: (t: Task, status: string) => void;
  onReview: (t: Task, d: "ACCEPT" | "REVISE" | "REJECT", comment: string) => void;
  onRevoke: (delegationId: string) => void;
}) {
  const [showCancelled, setShowCancelled] = useState(false);
  const [comment, setComment] = useState<Record<string, string>>({});
  const cols = showCancelled ? [...COLS, "CANCELLED" as const] : COLS;
  return (
    <div>
      {cols.map((col) => {
        const list = tasks.filter((t) => t.status === col);
        return (
          <section key={col} className="task-col" aria-label={TASK_STATUS[col][0]}>
            <div className="task-col-head"><h4>{TASK_STATUS[col][0]}</h4><span className="badge">{list.length}</span></div>
            {list.length === 0 && <p className="muted">해당 태스크가 없습니다.</p>}
            {list.map((t) => {
              const section = SECTIONS.find((s) => s.id === t.template_key);
              const a = t.owner === "COLLEAGUE" ? ACTOR.COLLEAGUE : t.owner === "JOINT" ? null : ACTOR.CANDIDATE;
              return (
                <article key={t.id} className={`task-card stack ${t.status === "REVIEW" ? "review" : ""}`}>
                  <div className="row">
                    {t.status === "REVIEW" && <Icon name="warning" />}
                    <strong style={{ color: "var(--color-heading)" }}>{t.title}</strong>
                    <span className="spacer" />
                    <span className={`badge ${TASK_STATUS[t.status][1]}`}>{TASK_STATUS[t.status][0]}</span>
                  </div>
                  <div className="row small">
                    <span className="owner">{a && <span className={`avatar ${a.avatar}`} aria-hidden="true">{a.initial}</span>}담당 {OWNER_LABEL[t.owner]}</span>
                    {section && <span className="badge">{section.title.replace(/^\d+\.\s*/, "")}</span>}
                    {t.delegation_id && <span className="badge info">분담 위임</span>}
                  </div>
                  {t.owner !== "COLLEAGUE" && !readOnly && (
                    <div className="row">
                      {t.status === "TODO" && <button className="btn btn-sm" onClick={() => onMove(t, "IN_PROGRESS")}>시작하기</button>}
                      {t.status === "IN_PROGRESS" && <button className="btn btn-sm" onClick={() => onMove(t, "DONE")}>완료로 표시</button>}
                      {t.status === "DONE" && <button className="btn btn-sm" onClick={() => onMove(t, "IN_PROGRESS")}>다시 열기</button>}
                    </div>
                  )}
                  {workingTaskIds.has(t.id) && <div className="row small"><span className="spin" aria-hidden="true" />이도현 님이 작성 중이에요. 완성되면 기획안 탭에 확인 요청이 옵니다.</div>}
                  {t.owner === "COLLEAGUE" && t.status === "IN_PROGRESS" && t.result?.rejected && !workingTaskIds.has(t.id) && !readOnly && (
                    <div className="stack">
                      <div className="row small"><span className="badge">초안 거절됨</span>문서는 바뀌지 않았어요. 수정 방향을 남기면 다시 작성해요.</div>
                      {t.result?.summary && <details><summary className="small">거절한 초안 보기</summary><div className="card-sub small" style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{t.result.summary}</div></details>}
                      <div className="field">
                        <label htmlFor={`rw-${t.id}`} className="small">수정 방향</label>
                        <textarea id={`rw-${t.id}`} className="textarea" style={{ minHeight: 56 }} value={comment[t.id] ?? ""}
                          onChange={(e) => setComment((c) => ({ ...c, [t.id]: e.target.value }))} placeholder="예: 효과가 확인되지 않은 부분은 빼고 사례 비교 기준 중심으로" />
                      </div>
                      <div className="row"><button className="btn btn-sm btn-primary" disabled={!(comment[t.id] ?? "").trim()} onClick={() => { onReview(t, "REVISE", comment[t.id] ?? ""); setComment((c) => ({ ...c, [t.id]: "" })); }}>다시 작성 요청</button></div>
                    </div>
                  )}
                  {t.owner === "COLLEAGUE" && t.status === "DONE" && t.result?.summary && (
                    <details>
                      <summary className="small">반영된 초안 · 추가 수정 요청</summary>
                      <div className="card-sub small" style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{t.result.summary}</div>
                      {!readOnly && !workingTaskIds.has(t.id) && (
                        <div className="stack" style={{ marginTop: 8 }}>
                          <textarea aria-label="추가 수정 방향" className="textarea" style={{ minHeight: 56 }} value={comment[t.id] ?? ""}
                            onChange={(e) => setComment((c) => ({ ...c, [t.id]: e.target.value }))} placeholder="더 고칠 점이 있으면 적어 주세요" />
                          <div><button className="btn btn-sm" disabled={!(comment[t.id] ?? "").trim()} onClick={() => { onReview(t, "REVISE", comment[t.id] ?? ""); setComment((c) => ({ ...c, [t.id]: "" })); }}>추가 수정 요청</button></div>
                        </div>
                      )}
                    </details>
                  )}
                  {t.owner === "COLLEAGUE" && t.status === "REVIEW" && !readOnly && (
                    <div className="stack">
                      {t.result?.summary && <div className="card-sub small" style={{ whiteSpace: "pre-wrap" }}>{t.result.summary}</div>}
                      <div className="field">
                        <label htmlFor={`rv-${t.id}`} className="small">검토 메모(선택)</label>
                        <textarea id={`rv-${t.id}`} className="textarea" style={{ minHeight: 56 }} value={comment[t.id] ?? ""}
                          onChange={(e) => setComment((c) => ({ ...c, [t.id]: e.target.value }))} />
                        <p className="help">자료와 대조한 근거가 있다면 함께 남겨 주세요. 수락이 검증 완료를 뜻하지는 않습니다.</p>
                      </div>
                      <div className="row">
                        <button className="btn btn-sm btn-primary" onClick={() => onReview(t, "ACCEPT", comment[t.id] ?? "")}>수락</button>
                        <button className="btn btn-sm" onClick={() => onReview(t, "REVISE", comment[t.id] ?? "")}>수정 요청</button>
                        <button className="btn btn-sm" onClick={() => onReview(t, "REJECT", comment[t.id] ?? "")}>기각</button>
                      </div>
                    </div>
                  )}
                  {t.owner === "COLLEAGUE" && t.delegation_id && ["TODO", "IN_PROGRESS"].includes(t.status) && !readOnly && (
                    <div><button className="btn btn-sm btn-tertiary" onClick={() => onRevoke(t.delegation_id!)}>위임 취소</button></div>
                  )}
                </article>
              );
            })}
          </section>
        );
      })}
      <button className="btn btn-tertiary btn-sm" style={{ marginTop: 12 }} onClick={() => setShowCancelled((v) => !v)}>
        {showCancelled ? "취소됨 숨기기" : "취소됨 보기"}
      </button>
    </div>
  );
}
