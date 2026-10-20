"use client";
import { useRouter } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { api, ApiError, loadMe, setCsrf } from "@/lib/api";

const CONSENT_ITEMS = [
  "업무 중 대화, 업무 분담과 태스크 변경, 산출물 수정 이력 같은 협업 행동이 기록되어 관찰에 사용됩니다.",
  "AI 동료(한서윤)와 팀장(박준호)은 가상 인물입니다. 진행은 시간이 아니라 행동(메시지·보드·문서 저장) 수에 따라 이어집니다.",
  "리포트는 점수·등급·합격 여부를 만들지 않으며, 최종 판단은 사람이 합니다.",
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
        if (me?.role === "CANDIDATE" && me.session_id) {
          const closed = await api(`/sessions/${me.session_id}`).then(() => false).catch((err) => err instanceof ApiError && err.code === "SESSION_CLOSED");
          if (closed) { router.replace(`/debrief/${me.session_id}`); return; }
          setSessionId(me.session_id);
        }
        else setError("초대 링크가 필요합니다.");
        return;
      }
      try {
        const r = await api<{ session_id: string; csrf_token: string }>("/auth/exchange", { method: "POST", json: { token } });
        setCsrf(r.csrf_token);
        setSessionId(r.session_id);
        try {
          const s = await api<{ session: { status: string } }>(`/sessions/${r.session_id}`);
          if (s.session.status !== "CREATED") router.replace(`/office/${r.session_id}`);
        } catch (err) {
          if (err instanceof ApiError && err.code === "SESSION_CLOSED") router.replace(`/debrief/${r.session_id}`);
          else throw err;
        }
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
    <main className="center-wrap">
      <div className="card center-card wide stack-lg">
        <span className="wordmark"><span className="wordmark-dot" aria-hidden="true" />Day Zero</span>
        <h1 className="display" style={{ fontSize: 28, lineHeight: "38px" }}>핏모아 운영팀 합류</h1>
        {error && <div className="alert error" role="alert"><Icon name="error" />{error}</div>}
        {!error && !sessionId && <p className="row muted"><span className="spin" />초대를 확인하는 중…</p>}
        {sessionId && !error && (
          <>
            <p>오늘 가상 피트니스 앱 회사 핏모아(FitMoa) 운영팀 신입으로 합류합니다. 박준호 팀장, 운영팀 1년차 한서윤(AI 동료)과 함께 다음 주 시작하는 친구 초대 이벤트의 고객 안내 자료를 준비합니다. 협업 상황 시뮬레이션이며 결과물 완성도보다 일하는 방식을 봅니다. 약 15~20분 걸립니다.</p>
            <section className="card-sub stack" aria-labelledby="consent-title">
              <h3 id="consent-title">시작 전 안내</h3>
              <ul className="checklist">{CONSENT_ITEMS.map((t) => <li key={t}>{t}</li>)}</ul>
            </section>
            <label className="row" style={{ fontWeight: 400 }}>
              <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} /> 위 내용을 확인했고 동의합니다.
            </label>
            <button className="btn btn-primary btn-lg btn-block" disabled={!checked || busy} onClick={start}>{busy ? "입장 중…" : "작업 공간 입장"}</button>
          </>
        )}
      </div>
    </main>
  );
}

export default function JoinPage() {
  return <Suspense><Join /></Suspense>;
}
