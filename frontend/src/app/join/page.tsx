"use client";
import { useRouter } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { api, ApiError, loadMe, setCsrf } from "@/lib/api";

const CONSENT_ITEMS = [
  "과제 진행 중 메시지·자료 열람·도구 사용·문서 수정 같은 행동이 기록됩니다.",
  "AI 동료·어시스턴트 사용 기록(요청, 조사 결과, 승인/거절)이 리포트에 포함됩니다.",
  "리포트는 점수나 합격 여부를 판정하지 않으며, 최종 판단은 사람이 합니다.",
  "로컬 데모 환경에 저장되며 자동 파기 기능은 아직 제공되지 않습니다.",
];

function Join() {
  const router = useRouter();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const token = new URLSearchParams(window.location.search).get("token");
    // URL에서 토큰을 즉시 제거
    window.history.replaceState(null, "", "/join");
    (async () => {
      if (!token) {
        const me = await loadMe();
        if (me?.role === "CANDIDATE" && me.session_id) setSessionId(me.session_id);
        else setError("초대 링크가 필요합니다.");
        return;
      }
      try {
        const r = await api<{ session_id: string; csrf_token: string }>("/auth/exchange", { method: "POST", json: { token } });
        setCsrf(r.csrf_token);
        setSessionId(r.session_id);
        const s = await api<{ session: { status: string } }>(`/sessions/${r.session_id}`);
        if (s.session.status !== "CREATED") router.replace(`/office/${r.session_id}`);
      } catch (e) {
        if (e instanceof ApiError && e.code === "ALREADY_USED") setError("이미 사용된 초대 링크입니다. 처음 입장한 브라우저에서 다시 열어 주세요.");
        else if (e instanceof ApiError && e.code === "INVITE_EXPIRED") setError("만료된 초대 링크입니다. 담당자에게 새 링크를 요청해 주세요.");
        else setError("초대를 확인하지 못했습니다.");
      }
    })();
  }, [router]);

  async function start() {
    if (!sessionId) return;
    setBusy(true);
    try {
      await api(`/sessions/${sessionId}/start`, { method: "POST", json: { consent: true } });
      router.push(`/office/${sessionId}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "시작하지 못했습니다");
      setBusy(false);
    }
  }

  return (
    <main className="center-card card stack" style={{ maxWidth: 560 }}>
      <h1><span className="brand-dot" />루프커머스 프로젝트 합류</h1>
      {error && <div className="alert error" role="alert">{error}</div>}
      {!error && !sessionId && <p className="muted">초대를 확인하는 중…</p>}
      {sessionId && !error && (
        <>
          <p>오늘 모아마켓 장바구니 이탈 개선 과제에 서비스 기획자로 합류합니다. 팀장 한서윤, AI 동료 이도현과 함께 일합니다. 시간 제한은 없습니다.</p>
          <h3>시작 전 안내</h3>
          <ul>{CONSENT_ITEMS.map((t) => <li key={t}>{t}</li>)}</ul>
          <label className="row" style={{ fontWeight: 400 }}>
            <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} /> 위 내용을 확인했고 동의합니다.
          </label>
          <button className="btn btn-primary" disabled={!checked || busy} onClick={start}>{busy ? "입장 중…" : "작업 공간 입장"}</button>
        </>
      )}
    </main>
  );
}

export default function JoinPage() {
  return <Suspense><Join /></Suspense>;
}
