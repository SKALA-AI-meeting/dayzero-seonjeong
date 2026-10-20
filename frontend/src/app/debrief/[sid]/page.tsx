"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { api, ApiError, loadMe } from "@/lib/api";

/** 디브리핑: 서윤의 실수와 일정 변경이 의도된 연출이었음을 알리고 소감을 받는다. 시뮬레이션 내용은 다시 보여주지 않는다. */
export default function DebriefPage() {
  const { sid } = useParams<{ sid: string }>();
  const [message, setMessage] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadMe().then(() => api<{ message: string; reflection: string | null }>(`/sessions/${sid}/debrief`))
      .then((d) => { setMessage(d.message); if (d.reflection) { setText(d.reflection); setSaved(true); } })
      .catch(() => setMessage("업무가 종료되었습니다."));
    try { Object.keys(localStorage).filter((k) => k.startsWith("dz-")).forEach((k) => localStorage.removeItem(k)); } catch { /* ignore */ }
  }, [sid]);

  async function submit() {
    setBusy(true); setError(null);
    try { await api(`/sessions/${sid}/debrief/reflection`, { method: "POST", json: { text } }); setSaved(true); }
    catch (e) { setError(e instanceof ApiError ? e.message : "저장하지 못했습니다"); }
    finally { setBusy(false); }
  }

  return (
    <main className="center-wrap">
      <div className="card center-card wide stack-lg">
        <span className="wordmark"><span className="wordmark-dot" aria-hidden="true" />Day Zero</span>
        <div className="row"><Icon name="check" /><h1>오늘 업무가 끝났습니다. 수고하셨습니다.</h1></div>
        <div className="alert neutral"><Icon name="info" /><p>{message ?? "불러오는 중…"}</p></div>
        <div className="field">
          <label htmlFor="reflection">소감</label>
          <textarea id="reflection" className="textarea" maxLength={2000} value={text} readOnly={saved}
            onChange={(e) => setText(e.target.value)} placeholder="어떤 생각으로 움직이셨는지 짧게 남겨 주세요." />
          <p className="help">한 번만 남길 수 있습니다. 남기지 않아도 됩니다.</p>
        </div>
        {error && <div className="alert error" role="alert"><Icon name="error" />{error}</div>}
        {saved ? <div className="alert success"><Icon name="check" />소감을 남겼습니다. 이 창을 닫으셔도 됩니다.</div>
          : <div><button className="btn btn-primary" disabled={busy || !text.trim()} onClick={submit}>{busy ? "저장 중…" : "소감 남기기"}</button></div>}
        <p className="help">결과는 담당자가 안내합니다.</p>
      </div>
    </main>
  );
}
