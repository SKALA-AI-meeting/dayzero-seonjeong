"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { api, loadMe } from "@/lib/api";

/** 시험 종료 화면: 보안을 위해 종료 안내만 표시하고 시험 내용(기획안·대화·자료)은 다시 보여주지 않는다. */
export default function DebriefPage() {
  const { sid } = useParams<{ sid: string }>();
  const [message, setMessage] = useState<string>("기획안이 제출되었습니다. 오늘 시험 수고하셨습니다.");

  useEffect(() => {
    loadMe().then(() => api<{ message: string }>(`/sessions/${sid}/debrief`)).then((d) => setMessage(d.message)).catch(() => undefined);
    try { Object.keys(localStorage).filter((k) => k.startsWith("dz-")).forEach((k) => localStorage.removeItem(k)); } catch { /* ignore */ }
  }, [sid]);

  const [title, ...rest] = message.split(". ");
  return (
    <main className="center-wrap">
      <div className="card center-card wide stack-lg" style={{ textAlign: "center" }}>
        <span className="wordmark" style={{ justifyContent: "center" }}><span className="wordmark-dot" aria-hidden="true" />Day Zero</span>
        <div className="row" style={{ justifyContent: "center" }}><Icon name="check" /><h1>{title}{rest.length ? "." : ""}</h1></div>
        <p>{rest.join(". ")}</p>
        <p className="help">이 창을 닫으셔도 됩니다. 결과는 담당자가 안내합니다.</p>
      </div>
    </main>
  );
}
