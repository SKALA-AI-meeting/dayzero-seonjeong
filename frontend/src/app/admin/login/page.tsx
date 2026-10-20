"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError, setCsrf } from "@/lib/api";

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
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "로그인에 실패했습니다");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="center-card card">
      <form className="stack" onSubmit={submit}>
        <h1><span className="brand-dot" />관리자 로그인</h1>
        <div>
          <label htmlFor="email">이메일</label>
          <input id="email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </div>
        <div>
          <label htmlFor="pw">비밀번호</label>
          <input id="pw" className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        {error && <div className="alert error" role="alert">오류: {error}</div>}
        <button className="btn btn-primary" disabled={busy}>{busy ? "로그인 중…" : "로그인"}</button>
      </form>
    </main>
  );
}
