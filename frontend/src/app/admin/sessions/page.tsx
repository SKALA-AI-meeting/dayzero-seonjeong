"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AdminShell } from "@/components/AdminShell";
import { Icon } from "@/components/Icon";
import { Modal } from "@/components/Overlay";
import { api, ApiError, loadMe } from "@/lib/api";

type Item = { id: string; alias: string; status: string; phase: string; report_status: string | null; created_at: string; submitted_at: string | null };
const STATUS: Record<string, [string, string]> = { CREATED: ["생성됨", ""], ACTIVE: ["진행 중", "info"], SUBMITTED: ["제출 완료", "success"] };
const PHASE: Record<string, string> = { BRIEF: "과제 확인", WORK: "업무 진행", REVIEW: "검토", CLOSED: "종료" };
const REPORT: Record<string, [string, string]> = { PENDING: ["대기", "warning"], RUNNING: ["생성 중", "info"], READY: ["준비됨", "success"], FAILED: ["실패", "error"] };
const DEMO_EVENTS: [string, string][] = [
  ["T-SPLIT", "00:10 업무 분담"], ["T-HELP", "00:30 도움 요청"], ["T-DELAY", "00:50 자료 지연"], ["T-INTERVIEW", "01:05 인터뷰 공개"],
  ["T-PIVOT", "01:10 대상 변경"], ["T-ERROR", "01:30 동료 오류"], ["T-DEADLINE", "01:50 마감 보고"], ["T-END", "02:00 종료·자동 제출"],
];
const kst = (iso: string) => new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });

export default function AdminSessions() {
  const router = useRouter();
  const [items, setItems] = useState<Item[] | null>(null);
  const [demo, setDemo] = useState(false);
  const [demoMsg, setDemoMsg] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [alias, setAlias] = useState("");
  const [invite, setInvite] = useState<{ url: string; expires: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await api<{ items: Item[]; demo_enabled: boolean }>("/sessions");
      setItems(r.items);
      setDemo(r.demo_enabled);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) router.push("/admin/login");
      else setError("세션 목록을 불러오지 못했습니다. 다시 시도해 주세요.");
    }
  }, [router]);

  useEffect(() => {
    loadMe().then((me) => (me?.role === "ADMIN" ? refresh() : router.push("/admin/login")));
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh, router]);

  async function createInvite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api<{ invite_url: string; expires_at: string }>("/invites", { method: "POST", json: { alias } });
      setInvite({ url: r.invite_url, expires: r.expires_at });
      setCopied(false);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "초대를 만들지 못했습니다");
    } finally { setBusy(false); }
  }
  function closeInvite() { setInviteOpen(false); setInvite(null); setAlias(""); }

  async function advance(id: string, ev: string) {
    try {
      const r = await api<{ fired: string[]; elapsed_min: number }>(`/sessions/${id}/demo/advance`, { method: "POST", json: { to_event: ev } });
      setDemoMsg(`발생한 이벤트: ${r.fired.join(", ") || "없음"} · 경과 ${Math.floor(r.elapsed_min)}분`);
      refresh();
    } catch (e) { setDemoMsg(e instanceof ApiError ? e.message : "시간 이동에 실패했습니다"); }
  }

  return (
    <AdminShell title="지원자 세션" actions={<button className="btn btn-primary btn-sm" onClick={() => setInviteOpen(true)}>새 초대 만들기</button>}>
      <div className="stack-lg">
        <p className="help">초대를 만들고 진행 및 제출 상태를 확인합니다.</p>
        {error && <div className="alert error" role="alert"><Icon name="error" /><span style={{ flex: 1 }}>{error}</span><button className="btn btn-sm" onClick={() => { setError(null); refresh(); }}>다시 시도</button></div>}
        {demo && <div className="alert warning"><Icon name="clock" /><div><div className="alert-title">시연 모드</div>진행 중인 세션의 시험 시계를 다음 이벤트로 옮길 수 있습니다. 지원자 화면에는 표시되지 않습니다.{demoMsg && <div className="small">{demoMsg}</div>}</div></div>}
        <div className="table-wrap">
          {items === null ? <p className="row muted" style={{ padding: 16 }}><span className="spin" />불러오는 중…</p> : items.length === 0 ? (
            <div style={{ padding: 24 }} className="stack"><p>아직 생성된 지원자 세션이 없습니다. 초대 링크를 만들어 첫 세션을 시작하세요.</p><div><button className="btn btn-primary btn-sm" onClick={() => setInviteOpen(true)}>새 초대 만들기</button></div></div>
          ) : (
            <table>
              <thead><tr><th>지원자</th><th>시나리오</th><th>진행 상태</th><th>현재 단계</th><th>리포트</th><th>시작 시각</th><th>작업</th></tr></thead>
              <tbody>
                {items.map((s) => (
                  <tr key={s.id}>
                    <td><div className="strong">{s.alias}</div><div className="muted num">{s.id.slice(-8)}</div></td>
                    <td className="small">모아런 재참여율 개선</td>
                    <td><span className={`badge ${STATUS[s.status]?.[1]}`}>{STATUS[s.status]?.[0] ?? s.status}</span></td>
                    <td className="small">{PHASE[s.phase] ?? s.phase}</td>
                    <td>{s.report_status ? <span className={`badge ${REPORT[s.report_status]?.[1]}`}>{REPORT[s.report_status]?.[0]}</span> : <span className="muted">—</span>}</td>
                    <td className="num small">{kst(s.created_at)}</td>
                    <td>
                      <div className="row">
                        {s.report_status ? <Link className="btn btn-sm" href={`/admin/reports/${s.id}`}>리포트 열기</Link> : <span className="muted">제출 전</span>}
                        {demo && s.status === "ACTIVE" && (
                          <select className="select" aria-label={`${s.alias} 시연: 이벤트로 이동`} defaultValue=""
                            onChange={(e) => { if (e.target.value) advance(s.id, e.target.value); e.target.value = ""; }}>
                            <option value="">시연: 이벤트로 이동…</option>
                            {DEMO_EVENTS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
                          </select>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
      <Modal open={inviteOpen} size="sm" title="새 초대 만들기" onClose={closeInvite}
        footer={invite ? <button className="btn btn-primary" onClick={closeInvite}>완료</button>
          : <><button className="btn" onClick={closeInvite}>취소</button><button className="btn btn-primary" form="invite-form" disabled={busy || !alias.trim()}>{busy ? "만드는 중…" : "초대 링크 만들기"}</button></>}>
        {invite ? (
          <div className="stack">
            <div className="alert success"><Icon name="check" />초대 링크를 만들었습니다. 만료: {kst(invite.expires)} (72시간)</div>
            <div className="field">
              <label htmlFor="invite-url">초대 링크</label>
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <input id="invite-url" className="input" readOnly value={invite.url} onFocus={(e) => e.target.select()} />
                <button className="btn" onClick={() => navigator.clipboard.writeText(invite.url).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); })}>{copied ? "복사됨" : "링크 복사"}</button>
              </div>
              <p className="help">이 링크는 원문 그대로 다시 확인할 수 없습니다. 안전한 채널로 전달하세요.</p>
            </div>
          </div>
        ) : (
          <form id="invite-form" onSubmit={createInvite} className="field">
            <label htmlFor="alias">지원자 별칭</label>
            <input id="alias" className="input" data-autofocus value={alias} onChange={(e) => setAlias(e.target.value)} placeholder="예: 지원자 A" required maxLength={60} />
            <p className="help">실명 대신 별칭을 사용합니다. 링크는 72시간 동안 1회 사용할 수 있습니다.</p>
          </form>
        )}
      </Modal>
    </AdminShell>
  );
}
