"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { api, ApiError, loadMe } from "@/lib/api";
import { COPY } from "@/lib/types";

type Ev = { event_id: string; time: string; description: string; status?: string };
type Debrief = { occurred_events: Ev[]; not_triggered: Ev[]; recording_notice: string };

/** 디브리핑 (DESIGN_GUIDE §4.13): 평가 결과는 표시하지 않고, 연출 상황과 기록 방식만 설명. */
export default function DebriefPage() {
  const { sid } = useParams<{ sid: string }>();
  const [d, setD] = useState<Debrief | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadMe().then(() => api<Debrief>(`/sessions/${sid}/debrief`)).then(setD)
      .catch((e) => setError(e instanceof ApiError ? e.message : "안내를 불러오지 못했습니다"));
  }, [sid]);

  return (
    <main className="center-wrap" style={{ alignItems: "flex-start" }}>
      <div className="center-card wide stack-lg">
        <span className="wordmark"><span className="wordmark-dot" aria-hidden="true" />Day Zero</span>
        {error && <div className="alert error" role="alert"><Icon name="error" />{error}</div>}
        {!d && !error && <p className="row muted"><span className="spin" />불러오는 중…</p>}
        {d && (
          <>
            <div className="stack">
              <div className="row"><Icon name="check" className="icon" /><h1>{COPY.submitted}</h1></div>
              <p>수고하셨습니다. 진행 중이던 AI 동료 작업과 확인 요청은 종료되었고, 제출한 기획안은 그대로 보관됩니다.</p>
            </div>
            <section className="card stack" aria-labelledby="debrief-title">
              <h2 id="debrief-title">오늘 일어난 상황 안내</h2>
              <p>{d.recording_notice}</p>
              <div className="table-wrap"><table>
                <thead><tr><th style={{ width: 80 }}>시각</th><th>상황</th></tr></thead>
                <tbody>
                  {d.occurred_events.map((e) => <tr key={e.event_id}><td className="num">{e.time}</td><td>{e.description}</td></tr>)}
                  {d.not_triggered.map((e) => <tr key={e.event_id}><td className="num muted">{e.time}</td><td><span className="muted">{e.description}</span> <span className="badge">{e.status}</span></td></tr>)}
                </tbody>
              </table></div>
              <p className="help">AI를 사용하지 않았거나 일부 상황이 일어나지 않은 것은 불리한 평가로 쓰이지 않습니다.</p>
            </section>
            <div className="row"><Link className="btn btn-primary" href={`/office/${sid}`}>제출한 기획안 보기</Link><span className="muted">결과는 담당자가 기록을 검토한 뒤 안내합니다.</span></div>
          </>
        )}
      </div>
    </main>
  );
}
