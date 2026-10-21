"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { Icon } from "@/components/Icon";
import { api, ApiError, loadMe } from "@/lib/api";
import { COPY } from "@/lib/types";

type Evidence = { kind: string; id: string; actor?: string; quote?: string; at?: string; turn?: number; artifact?: string; diff?: string[];
  action?: string; entity?: string };
type Criterion = { company_id: string; company_name: string | null; doc_id: string; doc_title: string | null; section: string; title: string;
  quote: string; score: number; text: string };
type Obs = { code: string; definition: string; polarity: "positive" | "caution" | "neutral"; event_id: string | null; subject: string | null;
  note: string | null; source: "AGENT" | "RULES"; estimated?: boolean; evidence: Evidence; linked_criterion?: Criterion };
type Comp = { key: string; label: string; status: "OBSERVED" | "INSUFFICIENT" | "NO_OPPORTUNITY"; status_label: string;
  related_events: { event_id: string; virtual_time: string; turn: number }[]; observations: Obs[]; notes: string[];
  evidence_summary?: { text: string; label: string } };
type Body = {
  scenario_title: string; generation_mode: string; ended_by: string; turn_count: number; virtual_time: string;
  timeline: { event_id: string; virtual_time: string; turn: number; skipped: boolean; reason: string | null }[];
  competencies: Comp[];
  planted_errors: { id: string; where: string; difficulty: string; fixed: boolean; fixed_by: string | null; codes: string[] }[];
  e2_change: { occurred: boolean; reflected: Record<string, boolean> };
  commitments: { text: string; status: string; event_id: string | null; registered_turn: number }[];
  final_board: { key: string; title: string; status: string; owner: string; eta: string | null }[];
  raw: { messages: { id: string; actor: string; content: string; turn: number; kind: string | null; event_id: string | null; label: string | null; at: string }[];
    revisions: { id: string; artifact: string; actor: string; version: number; turn: number; diff: string[] }[];
    approvals: { artifact: string; targets: string[]; status: string; diff: string[] }[] };
  reflection: string | null; limitations: string[];
  company?: { company_id: string; company_name: string | null; linked: number; status: string; note: string };
};
const EVENT: Record<string, string> = {
  E0: "스탠드업·분업", E1: "동료 도움 요청", E2: "팀장 요구사항 변경", E2B: "서윤 미반영", E3: "동료 급 이탈", E3B: "동료 복귀", E4: "마감 전 브리핑",
};
const STATUS: Record<string, [string, string]> = { OBSERVED: ["success", "check"], INSUFFICIENT: ["warning", "warning"], NO_OPPORTUNITY: ["", "info"] };
const POLARITY: Record<string, string> = { positive: "success", caution: "warning", neutral: "" };
const OWNER: Record<string, string> = { CANDIDATE: "지원자", COLLEAGUE: "한서윤", SPLIT: "나눠서", UNASSIGNED: "미정" };
const TASK: Record<string, string> = { TODO: "할 일", IN_PROGRESS: "진행 중", DONE: "완료" };
const STATE_COPY: Record<string, string> = { PENDING: "리포트를 준비하고 있습니다.", RUNNING: "관찰 코드와 근거를 연결하고 있습니다." };

function Diff({ lines }: { lines: string[] }) {
  if (!lines.length) return <span className="muted">변경 없음</span>;
  return <pre className="small" style={{ whiteSpace: "pre-wrap", margin: 0 }}>{lines.map((l, i) => (
    <span key={i} style={{ display: "block", color: l.startsWith("+") ? "#15803d" : l.startsWith("-") ? "#b91c1c" : undefined }}>{l}</span>))}</pre>;
}

function EvidenceView({ e }: { e: Evidence }) {
  if (e.kind === "message") return (
    <div className="card-sub small stack"><div className="row"><span className="strong">{e.actor}</span><span className="muted num">{e.at} · 턴 {e.turn}</span>
      <span className="spacer" /><a href={`#m-${e.id}`} className="small">원문 위치</a></div><div style={{ whiteSpace: "pre-wrap" }}>“{e.quote}”</div></div>);
  if (e.kind === "revision") return (
    <div className="card-sub small stack"><div className="row"><span className="strong">{e.actor}</span><span className="muted">{e.artifact} 수정 · 턴 {e.turn}</span></div><Diff lines={e.diff ?? []} /></div>);
  if (e.kind === "action") return <div className="card-sub small">행동 기록: {e.action} {e.entity ?? ""} · 턴 {e.turn}</div>;
  return <div className="card-sub small">{e.kind}: {e.id}</div>;
}

export default function ReportPage() {
  const { sid } = useParams<{ sid: string }>();
  const [rep, setRep] = useState<{ status: string; body: Body | null; error_code: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [companies, setCompanies] = useState<string[]>([]);
  const [companyId, setCompanyId] = useState("");

  const load = useCallback(async () => {
    try { setRep(await api(`/reports/${sid}`)); }
    catch (e) { setError(e instanceof ApiError ? e.message : "리포트를 불러오지 못했습니다"); }
  }, [sid]);
  useEffect(() => { loadMe().then(load); }, [load]);
  useEffect(() => {
    api<{ items: { company_id: string }[]; default: string }>("/companies")
      .then((r) => { setCompanies(r.items.map((i) => i.company_id)); setCompanyId((v) => v || r.default); }).catch(() => {});
  }, []);
  useEffect(() => { if (rep?.body?.company?.company_id) setCompanyId(rep.body.company.company_id); }, [rep?.body?.company?.company_id]);
  useEffect(() => {
    if (!rep || rep.status === "READY" || rep.status === "FAILED") return;
    const t = setTimeout(load, 2000);
    return () => clearTimeout(t);
  }, [rep, load]);

  async function retry(company?: string) {
    setBusy(true);
    try { await api(`/reports/${sid}/retry`, { method: "POST", ...(company ? { json: { company_id: company } } : {}) }); await load(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "다시 생성하지 못했습니다"); }
    finally { setBusy(false); }
  }

  const b = rep?.body;
  return (
    <AdminShell title="관찰 리포트" actions={<Link className="btn btn-sm" href="/admin/sessions">세션 목록</Link>}>
      <div className="stack-lg">
        {error && <div className="alert error" role="alert"><Icon name="error" />{error}</div>}
        {rep && rep.status !== "READY" && rep.status !== "FAILED" && <p className="row muted"><span className="spin" />{STATE_COPY[rep.status] ?? rep.status}</p>}
        {rep?.status === "FAILED" && (
          <div className="alert error" role="alert"><Icon name="error" /><span style={{ flex: 1 }}>{COPY.report_failed} ({rep.error_code})</span>
            <button className="btn btn-sm" disabled={busy} onClick={() => retry()}>다시 생성</button></div>
        )}
        {b && (
          <>
            <div className="alert neutral"><Icon name="info" /><div>{COPY.report_limit}</div></div>
            {companies.length > 0 && (
              <div className="card row" style={{ flexWrap: "wrap", gap: 8 }}>
                <span className="muted">회사 기준</span>
                <span className="strong">{b.company ? `${b.company.company_name ?? b.company.company_id} (${b.company.company_id})` : "연결 안 됨"}</span>
                {b.company?.status === "UNAVAILABLE" && <span className="badge warning">조항 서버 연결 실패</span>}
                <span className="spacer" />
                <label className="row small" style={{ gap: 6 }}>기준 선택
                  <select value={companyId} onChange={(e) => setCompanyId(e.target.value)} disabled={busy}>
                    {companies.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </label>
                <button className="btn btn-sm" disabled={busy || !companyId || rep?.status !== "READY"} onClick={() => retry(companyId)}>이 기준으로 다시 생성</button>
                <div className="small muted" style={{ flexBasis: "100%" }}>{b.company?.note ?? "회사 조항 연결은 근거 첨부이며 좋다·나쁘다 판정이 아닙니다"}</div>
              </div>
            )}
            <div className="summary-cards">
              <div className="card"><div className="muted">시나리오</div><div className="strong">{b.scenario_title}</div></div>
              <div className="card"><div className="muted">종료</div><div className="strong">{b.ended_by === "CANDIDATE" ? "지원자가 업무 종료" : "자동 종료"} · {b.virtual_time}</div></div>
              <div className="card"><div className="muted">진행 턴</div><div className="strong num">{b.turn_count}</div></div>
              <div className="card"><div className="muted">기록된 관찰 코드</div><div className="strong num">{b.competencies.reduce((n, c) => n + c.observations.length, 0)}</div></div>
            </div>

            <section className="stack"><h2>이벤트 타임라인</h2>
              <div className="table-wrap"><table>
                <thead><tr><th>이벤트</th><th>가상 시각</th><th className="num">턴</th><th>상태</th></tr></thead>
                <tbody>{b.timeline.map((t) => (
                  <tr key={t.event_id}><td>{t.event_id} {EVENT[t.event_id]}</td><td className="num">{t.virtual_time}</td><td className="num">{t.turn}</td>
                    <td>{t.skipped ? <span className="badge" title={t.reason ?? ""}>건너뜀 · {t.reason}</span> : <span className="badge success">발생</span>}</td></tr>))}</tbody>
              </table></div>
            </section>

            <section className="stack"><h2>역량별 관찰</h2>
              {b.competencies.map((c) => (
                <article key={c.key} className="card stack" aria-labelledby={`c-${c.key}`}>
                  <div className="row"><h3 id={`c-${c.key}`}>{c.label}</h3>
                    <span className={`badge ${STATUS[c.status][0]}`}><Icon name={STATUS[c.status][1]} />{c.status_label}</span><span className="spacer" />
                    <span className="muted">관련 이벤트: {c.related_events.length ? c.related_events.map((e) => `${e.event_id}(${e.virtual_time})`).join(", ") : "발생 없음"}</span>
                  </div>
                  {c.notes.map((n) => <div key={n} className="limits small"><Icon name="info" /> {n}</div>)}
                  {c.evidence_summary && <div className="interp small"><span className="badge info">{c.evidence_summary.label}</span> {c.evidence_summary.text}</div>}
                  {c.observations.length === 0 && <p className="muted">{c.status === "NO_OPPORTUNITY" ? "이 역량을 볼 이벤트가 발생하지 않았습니다." : "관련 이벤트는 발생했지만 기록된 행동 코드가 없습니다. 부정으로 해석하지 않습니다."}</p>}
                  {c.observations.map((o, i) => (
                    <div key={i} className="stack" style={{ borderTop: i ? "1px solid var(--color-border)" : undefined, paddingTop: i ? 12 : 0 }}>
                      <div className="row">
                        <span className={`badge ${POLARITY[o.polarity]}`}>{o.code}</span>
                        <span className="strong">{o.definition}</span>
                        <span className="spacer" />
                        {o.event_id && <span className="badge">{o.event_id} {EVENT[o.event_id]}</span>}
                        {o.subject && /^(PE|E2)/.test(o.subject) && <span className="badge">{o.subject}</span>}
                        {o.estimated && <span className="badge warning" title="분기 라벨을 LLM이 정했고 규칙으로 확정되지 않았습니다. 원문을 확인하세요.">LLM 추정</span>}
                        <span className="muted">{o.source === "AGENT" ? "대화 분기" : "로그 규칙"}</span>
                      </div>
                      {o.note && <p className="small muted">{o.note}</p>}
                      <EvidenceView e={o.evidence} />
                      {o.linked_criterion && (
                        <div className="card-sub small stack" aria-label="연결된 회사 조항">
                          <div className="row"><span className="badge info">{o.linked_criterion.company_name ?? o.linked_criterion.company_id} · {o.linked_criterion.section}</span>
                            <span>{o.linked_criterion.text}</span></div>
                          <blockquote style={{ margin: 0, paddingLeft: 10, borderLeft: "3px solid var(--color-border)", whiteSpace: "pre-wrap" }}>{o.linked_criterion.quote}</blockquote>
                        </div>
                      )}
                    </div>
                  ))}
                </article>
              ))}
            </section>

            <section className="stack"><h2>심어둔 오류·변경 반영·약속</h2>
              <div className="table-wrap"><table>
                <thead><tr><th>오류</th><th>위치</th><th>난이도</th><th>최종 상태</th><th>관련 코드</th></tr></thead>
                <tbody>{b.planted_errors.map((p) => (
                  <tr key={p.id}><td>{p.id}</td><td className="small">{p.where}</td><td>{p.difficulty}</td>
                    <td>{p.fixed ? <span className="badge success">수정됨 · {p.fixed_by}</span> : <span className="badge">남아 있음</span>}</td>
                    <td>{p.codes.join(", ") || <span className="muted">—</span>}</td></tr>))}</tbody>
              </table></div>
              {b.e2_change.occurred && <p className="small">E2 변경(피초대자 2,000P) 반영: {Object.entries(b.e2_change.reflected).map(([k, v]) => `${k} ${v ? "반영" : "미반영"}`).join(" · ")}</p>}
              {b.commitments.length > 0 && <ul className="checklist small">{b.commitments.map((c, i) => (
                <li key={i}>“{c.text}” — 턴 {c.registered_turn} 등록 · <span className={`badge ${c.status === "KEPT" ? "success" : c.status === "BROKEN" ? "warning" : ""}`}>{c.status === "KEPT" ? "이행" : c.status === "BROKEN" ? "미이행" : "판정 전"}</span></li>))}</ul>}
              <div className="table-wrap"><table>
                <thead><tr><th>종료 시 태스크</th><th>담당</th><th>상태</th><th>예상 시각</th></tr></thead>
                <tbody>{b.final_board.map((t) => <tr key={t.key}><td>{t.key} {t.title}</td><td>{OWNER[t.owner] ?? t.owner}</td><td>{TASK[t.status] ?? t.status}</td><td className="num">{t.eta ?? "—"}</td></tr>)}</tbody>
              </table></div>
            </section>

            <section className="stack"><h2>지원자 소감</h2>
              {b.reflection ? <div className="card-sub" style={{ whiteSpace: "pre-wrap" }}>{b.reflection}</div> : <p className="muted">남기지 않았습니다.</p>}
            </section>

            <section className="stack"><h2>원자료</h2>
              <details><summary className="strong">대화 전체 ({b.raw.messages.length})</summary>
                <div className="table-wrap" style={{ marginTop: 8 }}><table>
                  <thead><tr><th>턴</th><th>시각</th><th>보낸 사람</th><th>내용</th><th>구분</th></tr></thead>
                  <tbody>{b.raw.messages.map((m) => (
                    <tr key={m.id} id={`m-${m.id}`}><td className="num">{m.turn}</td><td className="num">{m.at}</td><td className="small">{m.actor}</td>
                      <td style={{ whiteSpace: "pre-wrap" }}>{m.content}</td>
                      <td className="small muted">{m.kind === "SCENARIO_EVENT" ? `이벤트 ${m.event_id}` : m.kind === "SCENARIO_BRANCH" ? `분기 ${m.label}` : m.kind ?? ""}</td></tr>))}</tbody>
                </table></div>
              </details>
              <details><summary className="strong">산출물 수정 이력 ({b.raw.revisions.length})</summary>
                <div className="stack" style={{ marginTop: 8 }}>{b.raw.revisions.map((r) => (
                  <div key={r.id} className="card-sub small stack"><div className="row"><span className="strong">{r.artifact} v{r.version}</span><span className="muted">{r.actor} · 턴 {r.turn}</span></div><Diff lines={r.diff} /></div>))}</div>
              </details>
              <details><summary className="strong">서윤 수정안 승인 카드 ({b.raw.approvals.length})</summary>
                <div className="stack" style={{ marginTop: 8 }}>{b.raw.approvals.map((a, i) => (
                  <div key={i} className="card-sub small stack"><div className="row"><span className="strong">{a.artifact}</span><span className="badge">{a.status}</span><span className="muted">{a.targets.join(", ")}</span></div><Diff lines={a.diff} /></div>))}</div>
              </details>
            </section>
            <ul className="checklist small muted">{b.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
          </>
        )}
      </div>
    </AdminShell>
  );
}
