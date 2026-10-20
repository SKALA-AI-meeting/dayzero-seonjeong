"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError, loadMe } from "@/lib/api";

type Ev = { event_id: string; time: string; description: string; status?: string };
type Debrief = { occurred_events: Ev[]; not_triggered: Ev[]; recording_notice: string };

export default function DebriefPage() {
  const { sid } = useParams<{ sid: string }>();
  const [d, setD] = useState<Debrief | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadMe().then(() => api<Debrief>(`/sessions/${sid}/debrief`)).then(setD)
      .catch((e) => setError(e instanceof ApiError ? e.message : "디브리핑을 불러오지 못했습니다"));
  }, [sid]);

  return (
    <main className="page stack" style={{ maxWidth: 760 }}>
      <h1><span className="brand-dot" />수고하셨습니다</h1>
      {error && <div className="alert error" role="alert">{error}</div>}
      {!d && !error && <p className="muted">불러오는 중…</p>}
      {d && (
        <>
          <div className="alert success">기획안이 제출되었습니다.</div>
          <div className="card stack">
            <h3>오늘 일어난 상황 안내</h3>
            <p className="muted" style={{ margin: 0 }}>{d.recording_notice}</p>
            <table>
              <thead><tr><th style={{ width: 70 }}>시각</th><th>상황</th></tr></thead>
              <tbody>
                {d.occurred_events.map((e) => <tr key={e.event_id}><td>{e.time}</td><td>{e.description}</td></tr>)}
                {d.not_triggered.map((e) => <tr key={e.event_id}><td className="muted">{e.time}</td><td className="muted">{e.description} <span className="badge">{e.status}</span></td></tr>)}
              </tbody>
            </table>
          </div>
          <p className="muted">결과는 담당자가 관찰 기록을 검토한 뒤 안내합니다. 이 창은 닫으셔도 됩니다.</p>
        </>
      )}
    </main>
  );
}
