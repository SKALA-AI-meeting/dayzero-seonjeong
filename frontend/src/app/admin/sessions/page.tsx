"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, loadMe } from "@/lib/api";

type Item = { id: string; alias: string; status: string; phase: string; report_status: string | null; created_at: string };
const statusLabel: Record<string, [string, string]> = {
  CREATED: ["입장 전", ""], ACTIVE: ["진행 중", "info"], SUBMITTED: ["제출됨", "success"],
};
const reportLabel: Record<string, [string, string]> = {
  PENDING: ["리포트 대기", "warning"], RUNNING: ["리포트 생성 중", "info"], READY: ["리포트 준비", "success"], FAILED: ["리포트 실패", "error"],
};

const DEMO_EVENTS: [string, string][] = [
  ["T-SPLIT", "00:10 업무 분담"], ["T-HELP", "00:30 도움 요청"], ["T-DELAY", "00:50 자료 지연"], ["T-INTERVIEW", "01:05 인터뷰 공개"],
  ["T-PIVOT", "01:10 대상 변경"], ["T-ERROR", "01:30 동료 오류"], ["T-DEADLINE", "01:50 마감 보고"], ["T-END", "02:00 종료·자동 제출"],
];

export default function AdminSessions() {
  const router = useRouter();
  const [items, setItems] = useState<Item[] | null>(null);
  const [demo, setDemo] = useState(false);
  const [demoMsg, setDemoMsg] = useState<string | null>(null);
  const [alias, setAlias] = useState("");
  const [invite, setInvite] = useState<{ url: string; expires: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await api<{ items: Item[]; demo_enabled: boolean }>("/sessions");
      setItems(r.items);
      setDemo(r.demo_enabled);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) router.push("/admin/login");
      else setError("세션 목록을 불러오지 못했습니다");
    }
  }, [router]);

  useEffect(() => {
    loadMe().then((me) => (me?.role === "ADMIN" ? refresh() : router.push("/admin/login")));
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh, router]);

  async function createInvite(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const r = await api<{ invite_url: string; expires_at: string }>("/invites", { method: "POST", json: { alias } });
      setInvite({ url: r.invite_url, expires: r.expires_at });
      setAlias("");
      setCopied(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "초대 생성 실패");
    }
  }

  async function advance(id: string, ev: string) {
    try {
      const r = await api<{ fired: string[]; elapsed_min: number }>(`/sessions/${id}/demo/advance`, { method: "POST", json: { to_event: ev } });
      setDemoMsg(`발생: ${r.fired.join(", ") || "없음"} (경과 ${Math.floor(r.elapsed_min)}분)`);
      refresh();
    } catch (e) {
      setDemoMsg(e instanceof ApiError ? e.message : "시간 이동 실패");
    }
  }

  async function logout() {
    await api("/auth/logout", { method: "POST", json: {} }).catch(() => undefined);
    router.push("/admin/login");
  }

  return (
    <main className="page stack">
      <div className="row"><h1><span className="brand-dot" />지원자 세션</h1><span className="spacer" /><button className="btn btn-sm" onClick={logout}>로그아웃</button></div>
      <form className="card row" onSubmit={createInvite}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <label htmlFor="alias">지원자 별칭</label>
          <input id="alias" className="input" value={alias} onChange={(e) => setAlias(e.target.value)} placeholder="예: 지원자 A" required maxLength={60} />
        </div>
        <button className="btn btn-primary" style={{ alignSelf: "flex-end" }}>초대 링크 만들기</button>
      </form>
      {invite && (
        <div className="alert success stack" role="status">
          <div>초대 링크가 생성되었습니다. 이 링크는 지금 한 번만 표시됩니다(만료 {new Date(invite.expires).toLocaleString("ko-KR")}).</div>
          <div className="row">
            <input className="input" readOnly value={invite.url} aria-label="초대 링크" style={{ flex: 1 }} />
            <button className="btn btn-sm" onClick={() => navigator.clipboard.writeText(invite.url).then(() => setCopied(true))}>{copied ? "복사됨" : "복사"}</button>
          </div>
        </div>
      )}
      {error && <div className="alert error" role="alert">오류: {error}</div>}
      {demo && <div className="alert warning">시연 모드(APP_ENV=development): 진행 중 세션의 시간을 다음 이벤트로 이동할 수 있습니다. 지원자 화면에는 표시되지 않습니다.{demoMsg && <> · {demoMsg}</>}</div>}
      <div className="card">
        {items === null ? <p className="muted">불러오는 중…</p> : items.length === 0 ? <p className="muted">아직 입장한 지원자가 없습니다.</p> : (
          <table>
            <thead><tr><th>별칭</th><th>상태</th><th>리포트</th><th>생성</th><th /></tr></thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.id}>
                  <td>{s.alias}</td>
                  <td><span className={`badge ${statusLabel[s.status]?.[1] ?? ""}`}>{statusLabel[s.status]?.[0] ?? s.status}</span></td>
                  <td>{s.report_status ? <span className={`badge ${reportLabel[s.report_status]?.[1]}`}>{reportLabel[s.report_status]?.[0]}</span> : <span className="muted">—</span>}</td>
                  <td className="muted">{new Date(s.created_at).toLocaleString("ko-KR")}</td>
                  <td className="row">
                    {s.report_status && <Link className="btn btn-sm" href={`/admin/reports/${s.id}`}>리포트 열기</Link>}
                    {demo && s.status === "ACTIVE" && (
                      <select aria-label="시연: 이벤트로 이동" defaultValue="" onChange={(e) => { if (e.target.value) advance(s.id, e.target.value); e.target.value = ""; }}>
                        <option value="">시연: 이벤트로 이동…</option>
                        {DEMO_EVENTS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                      </select>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </main>
  );
}
