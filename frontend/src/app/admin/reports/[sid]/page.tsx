"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { Icon } from "@/components/Icon";
import { Drawer } from "@/components/Overlay";
import { api, ApiError, loadMe } from "@/lib/api";
import { COPY } from "@/lib/types";

type Ref = { kind: string; id: string; quote: string | null };
type Fact = { text: string; at?: string | null; created_at?: string; event_id?: string; refs: Ref[] };
type Situation = { event_id: string | null; situation: string; status: string; at: string | null };
type Area = { dimension: string; label: string; status: string; situations: Situation[]; facts: Fact[]; limits: string;
  interpretation: { text: string; label: string } | null; follow_up?: string; usage?: Record<string, number> };
type Body = {
  generation_mode: string; policy_version: string; scenario_id: string; submitted_by: string;
  timeline: { event_id: string; at: string; situation: string }[];
  areas: Area[]; split_history: { kind: string; assignments: Record<string, string>; at: string }[];
  final_artifact: { version: number; empty_sections: string[] }; limitations: string[];
};
const STATUS: Record<string, [string, string, string]> = {
  OBSERVED: ["관찰됨", "success", "check"], INSUFFICIENT_EVIDENCE: ["관련 행동 근거 부족", "warning", "warning"],
  NO_OPPORTUNITY: ["관찰 기회 없음", "", "info"], NOT_USED: ["사용하지 않음", "", "info"],
};
const KIND: Record<string, string> = { message: "대화", action: "행동", artifact_revision: "문서 수정", tool_call: "도구 호출" };
const STATE_COPY: Record<string, string> = { PENDING: "제출 내용을 정리할 준비를 하고 있습니다.", RUNNING: "행동 기록과 근거를 연결하고 있습니다." };

function StatusBadge({ s }: { s: string }) {
  const v = STATUS[s] ?? [s, "", "info"];
  return <span className={`badge ${v[1]}`}><Icon name={v[2]} />{v[0]}</span>;
}

export default function ReportPage() {
  const { sid } = useParams<{ sid: string }>();
  const [r, setR] = useState<{ status: string; body: Body | null } | null>(null);
  const [alias, setAlias] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<{ fact: Fact; area: string } | null>(null);

  const load = useCallback(async () => {
    try { setR(await api<{ status: string; body: Body | null }>(`/reports/${sid}`)); }
    catch (e) { setError(e instanceof ApiError && e.status !== 503 ? "리포트를 찾을 수 없습니다." : "리포트를 불러오지 못했습니다."); }
  }, [sid]);
  useEffect(() => {
    loadMe().then(() => { load(); api<{ items: { id: string; alias: string }[] }>("/sessions").then((x) => setAlias(x.items.find((i) => i.id === sid)?.alias ?? "")).catch(() => undefined); });
  }, [sid, load]);
  useEffect(() => {
    if (!r || r.status === "READY" || r.status === "FAILED") return;
    const t = setTimeout(load, 2000);
    return () => clearTimeout(t);
  }, [r, load]);

  async function retry() {
    try { await api(`/reports/${sid}/retry`, { method: "POST", json: {} }); load(); } catch { setError("다시 생성하지 못했습니다."); }
  }

  const b = r?.body;
  const counts = b ? {
    observed: b.areas.filter((a) => a.status === "OBSERVED").length,
    noOpp: b.areas.filter((a) => a.status === "NO_OPPORTUNITY").length,
    events: b.timeline.filter((t) => !["T-KICKOFF", "T-INTERVIEW", "T-END"].includes(t.event_id)).length,
  } : null;

  return (
    <AdminShell title="행동 근거 기반 평가 리포트" actions={<Link className="btn btn-sm" href="/admin/sessions">세션 목록</Link>}>
      <div className="stack-lg" style={{ maxWidth: 1080 }}>
        {error && <div className="alert error" role="alert"><Icon name="error" />{error}</div>}
        {r && (r.status === "PENDING" || r.status === "RUNNING") && <div className="alert" role="status"><span className="spin" />{STATE_COPY[r.status]}</div>}
        {r?.status === "FAILED" && <div className="alert error"><Icon name="error" /><span style={{ flex: 1 }}>{COPY.report_failed}</span><button className="btn btn-sm" onClick={retry}>다시 생성</button></div>}
        {b && counts && (
          <>
            <div className="page-head">
              <div className="stack" style={{ marginTop: 0 }}>
                <h2>{alias || "지원자"}</h2>
                <p className="muted">시나리오 {b.scenario_id} · 정책 {b.policy_version} · 생성 방식 {b.generation_mode === "RULES_FALLBACK" ? "규칙 기반 대체" : "AI + 규칙"} ·
                  {b.submitted_by === "CANDIDATE" ? " 지원자 직접 제출" : " 시간 종료 자동 제출"} · 최종 기획안 v{b.final_artifact.version}</p>
              </div>
            </div>
            <div className="alert neutral"><Icon name="info" /><div>{COPY.report_limit} 점수·순위·합격 여부를 만들지 않으며 판단은 검토자가 합니다.</div></div>
            {b.generation_mode === "RULES_FALLBACK" && <div className="alert"><Icon name="info" />이 리포트는 기록된 사실만 규칙으로 정리했습니다. AI 해석은 포함되지 않았습니다.</div>}
            <div className="summary-cards">
              <div className="card"><div className="muted">관찰된 영역</div><div className="display num">{counts.observed}<span className="small"> / 5</span></div></div>
              <div className="card"><div className="muted">관찰 기회 없음</div><div className="display num">{counts.noOpp}</div></div>
              <div className="card"><div className="muted">발생한 상황</div><div className="display num">{counts.events}</div></div>
              <div className="card"><div className="muted">빈 섹션</div><div className="display num">{b.final_artifact.empty_sections.length}</div></div>
            </div>
            <section className="card stack" aria-labelledby="tl-title">
              <h3 id="tl-title">관찰 범위 및 발생 상황</h3>
              <div className="table-wrap"><table>
                <thead><tr><th style={{ width: 80 }}>시각</th><th>상황</th></tr></thead>
                <tbody>{b.timeline.map((e) => <tr key={e.event_id}><td className="num">{e.at}</td><td>{e.situation}</td></tr>)}</tbody>
              </table></div>
              {b.split_history.length > 0 && <p className="small">업무 분담 변경: {b.split_history.map((s) => `${s.at} ${s.kind === "SPLIT_CONFIRMED" ? "확정" : "조정 요청"}`).join(" → ")}</p>}
            </section>
            <h3>행동 요소</h3>
            {b.areas.map((a) => (
              <section key={a.dimension} className="card stack" aria-labelledby={`area-${a.dimension}`}>
                <div className="row"><h3 id={`area-${a.dimension}`}>{a.label}</h3><span className="spacer" /><StatusBadge s={a.status} /></div>
                <dl className="kv">
                  <dt>관찰 기회</dt>
                  <dd><ul className="checklist" style={{ paddingLeft: 16 }}>{a.situations.map((s, i) => <li key={i}><span className="num strong">{s.at ? `${s.at} ` : ""}</span>{s.situation} <StatusBadge s={s.status} /></li>)}</ul></dd>
                  <dt>실제 행동</dt>
                  <dd>
                    {a.facts.length === 0 ? <span className="muted">{a.limits}</span> : (
                      <div className="table-wrap"><table>
                        <thead><tr><th style={{ width: 70 }}>시각</th><th>행동</th><th style={{ width: 120 }}>원문 근거</th></tr></thead>
                        <tbody>{a.facts.map((f, i) => (
                          <tr key={i}>
                            <td className="num">{f.at ?? (f.created_at ? new Date(f.created_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" }) : "")}</td>
                            <td>{f.text}</td>
                            <td><button className="chip" onClick={() => setEvidence({ fact: f, area: a.label })}><Icon name="doc" />{KIND[f.refs[0]?.kind] ?? "기록"} #{f.refs[0]?.id.slice(0, 6)}</button></td>
                          </tr>
                        ))}</tbody>
                      </table></div>
                    )}
                    {a.usage && <p className="help">어시스턴트 요청 {a.usage.assistant_requests}회 · 도구 호출 {a.usage.assistant_tool_calls}회 (사용량만으로 평가하지 않음)</p>}
                  </dd>
                  <dt>제한된 해석</dt>
                  <dd className="interp">{a.interpretation ? <><span className="badge info">AI 추정</span> {a.interpretation.text}</> : <span className="small">규칙 기반 리포트라 해석을 생성하지 않았습니다. 원문 근거를 보고 판단해 주세요.</span>}</dd>
                  {a.follow_up && <><dt>후속 확인점</dt><dd className="small">{a.follow_up}</dd></>}
                  <dt>한계</dt>
                  <dd className="limits small">{a.limits}</dd>
                </dl>
              </section>
            ))}
            <section className="card stack"><h3>한계 및 후속 확인점</h3><ul className="checklist">{b.limitations.map((l) => <li key={l}>{l}</li>)}</ul></section>
          </>
        )}
      </div>
      <Drawer open={!!evidence} title="원문 근거" onClose={() => setEvidence(null)}>
        {evidence && (
          <div className="stack">
            <p className="muted">{evidence.area} · {KIND[evidence.fact.refs[0]?.kind] ?? "기록"} · {evidence.fact.at ?? ""}</p>
            <dl className="kv">
              <dt>원문 ID</dt><dd className="num small" style={{ overflowWrap: "anywhere" }}>{evidence.fact.refs.map((x) => `${x.kind}:${x.id}`).join(", ")}</dd>
              <dt>작성자</dt><dd>지원자</dd>
              <dt>기록 시각</dt><dd className="num">{evidence.fact.created_at ? new Date(evidence.fact.created_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", hour12: false }) : "—"}</dd>
            </dl>
            <div className="card-sub doc-body">{evidence.fact.refs[0]?.quote ?? evidence.fact.text}</div>
          </div>
        )}
      </Drawer>
    </AdminShell>
  );
}
