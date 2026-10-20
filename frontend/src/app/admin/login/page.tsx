"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Icon } from "@/components/Icon";
import { api, setCsrf } from "@/lib/api";

export default function AdminLogin() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@dayzero.local");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ csrf_token: string }>("/auth/login", { method: "POST", json: { email, password } });
      setCsrf(r.csrf_token);
      router.push("/admin/sessions");
    } catch {
      setError("이메일 또는 비밀번호를 확인해 주세요.");
      setBusy(false);
    }
  }

  return (
    <main className="center-wrap">
      <form className="card center-card stack" onSubmit={submit} noValidate aria-describedby={error ? "login-error" : undefined}>
        <span className="wordmark"><span className="wordmark-dot" aria-hidden="true" />Day Zero</span>
        <div><h1>Day Zero 관리자</h1><p className="help">초대를 만들고 지원자 세션과 관찰 리포트를 확인합니다.</p></div>
        {error && <div className="alert error" role="alert" id="login-error"><Icon name="error" />{error}</div>}
        <div className="field">
          <label htmlFor="email">이메일</label>
          <input id="email" className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required aria-invalid={!!error} />
        </div>
        <div className="field">
          <label htmlFor="pw">비밀번호</label>
          <input id="pw" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required aria-invalid={!!error} />
        </div>
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? "로그인 중…" : "로그인"}</button>
      </form>
    </main>
  );
}
