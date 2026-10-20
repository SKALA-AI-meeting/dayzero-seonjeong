"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError, loadMe } from "@/lib/api";

type Ref = { kind: string; id: string; quote: string | null };
type Fact = { text: string; at?: string | null; created_at?: string; event_id?: string; refs: Ref[] };
type Situation = { event_id: string | null; situation: string; status: string; at: string | null };
type Area = { dimension: string; label: string; status: string; situations: Situation[]; facts: Fact[]; limits: string; usage?: Record<string, number> };
type Body = {
  generation_mode: string; submitted_by: string; timeline: { event_id: string; at: string; situation: string }[];
  areas: Area[]; split_history: { kind: string; assignments: Record<string, string>; at: string }[];
  final_artifact: { version: number; empty_sections: string[] }; limitations: string[];
};
const STATUS: Record<string, [string, string]> = {
  OBSERVED: ["관찰됨", "success"], INSUFFICIENT_EVIDENCE: ["관련 행동 근거 부족", "warning"],
  NO_OPPORTUNITY: ["관찰 기회 없음", ""], NOT_USED: ["사용하지 않음", ""],
};

export default function ReportPage() {
  const { sid } = useParams<{ sid: string }>();
  const [r, setR] = useState<{ status: string; body: Body | null } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let t: ReturnType<typeof setTimeout>;
    const load = () => api<{ status: string; body: Body | null }>(`/reports/${sid}`).then((x) => {
      setR(x);
      if (x.status !== "READY" && x.status !== "FAILED") t = setTimeout(load, 2000);
    }).catch((e) => setError(e instanceof ApiError ? e.message : "리포트를 불러오지 못했습니다"));
    loadMe().then(load);
    return () => clearTimeout(t);
  }, [sid]);

  const b = r?.body;
  return (
    <main className="page stack">
      <div className="row"><Link className="btn btn-sm" href="/admin/sessions">← 세션 목록</Link><h1 style={{ margin: 0 }}>관찰 리포트</h1></div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {r && r.status !== "READY" && <div className="alert">리포트 상태: {r.status}</div>}
      {b && (
        <>
          <div className="alert">
            점수·등급·순위·합격 여부를 만들지 않습니다. 기록된 행동과 근거만 정리했으며 해석과 판단은 검토자가 합니다.
            생성 방식: {b.generation_mode} · 제출: {b.submitted_by === "CANDIDATE" ? "지원자 직접 제출" : "시간 종료 자동 제출"} ·
            최종 기획안 v{b.final_artifact.version}{b.final_artifact.empty_sections.length > 0 && ` · 빈 섹션: ${b.final_artifact.empty_sections.join(", ")}`}
          </div>
          <div className="card stack">
            <h3>이벤트 발생 시각</h3>
            <table><tbody>{b.timeline.map((e) => <tr key={e.event_id}><td style={{ width: 70 }}>{e.at}</td><td>{e.situation}</td></tr>)}</tbody></table>
            {b.split_history.length > 0 && (
              <div className="muted">업무 분담 변경: {b.split_history.map((s) => `${s.at} ${s.kind === "SPLIT_CONFIRMED" ? "확정" : "조정 요청"}`).join(" → ")}</div>
            )}
          </div>
          {b.areas.map((a) => (
            <section key={a.dimension} className="card stack" aria-label={a.label}>
              <div className="row"><h2 style={{ margin: 0 }}>{a.label}</h2><span className={`badge ${STATUS[a.status]?.[1]}`}>{STATUS[a.status]?.[0] ?? a.status}</span></div>
              <div>
                <h4>발생 상황</h4>
                <ul>{a.situations.map((s, i) => <li key={i}>{s.at && <strong>{s.at} </strong>}{s.situation} <span className={`badge ${STATUS[s.status]?.[1]}`}>{STATUS[s.status]?.[0] ?? s.status}</span></li>)}</ul>
              </div>
              <div>
                <h4>실제 관찰된 행동과 근거</h4>
                {a.facts.length === 0 ? <p className="muted">{a.limits}</p> : (
                  <table>
                    <thead><tr><th style={{ width: 70 }}>시각</th><th>행동</th><th style={{ width: 140 }}>근거 ID</th></tr></thead>
                    <tbody>
                      {a.facts.map((f, i) => (
                        <tr key={i}>
                          <td>{f.at ?? (f.created_at ? new Date(f.created_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }) : "")}</td>
                          <td>{f.text}</td>
                          <td className="muted" title={f.refs.map((x) => `${x.kind}:${x.id}`).join("\n")}>{f.refs[0]?.kind}:{f.refs[0]?.id.slice(0, 8)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              {a.usage && <div className="muted">어시스턴트 요청 {a.usage.assistant_requests}회 · 도구 호출 {a.usage.assistant_tool_calls}회 (사용량만으로 평가하지 않음)</div>}
              <div className="muted">한계: {a.limits}</div>
            </section>
          ))}
          <div className="card"><h4>리포트 한계</h4><ul>{b.limitations.map((l) => <li key={l}>{l}</li>)}</ul></div>
        </>
      )}
    </main>
  );
}
