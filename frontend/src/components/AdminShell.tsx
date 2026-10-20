"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";

/** 관리자 셸 (DESIGN_GUIDE §5.1): 좌측 224px 내비 + 상단 64px 헤더. */
export function AdminShell({ title, actions, children }: { title: string; actions?: React.ReactNode; children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  async function logout() {
    await api("/auth/logout", { method: "POST", json: {} }).catch(() => undefined);
    router.push("/admin/login");
  }
  return (
    <div className="admin">
      <a href="#admin-main" className="skip-link">주요 콘텐츠로 이동</a>
      <nav className="admin-nav" aria-label="관리자 메뉴">
        <Link href="/admin/sessions" className="wordmark"><span className="wordmark-dot" aria-hidden="true" />Day Zero</Link>
        <Link href="/admin/sessions" className="nav-item" aria-current={path.startsWith("/admin/sessions") || path.startsWith("/admin/reports")}>지원자 세션</Link>
        <div className="muted" style={{ padding: "12px 8px 0" }}>시나리오: 루프랩 모아런 재참여율 개선(읽기 전용)</div>
      </nav>
      <div className="admin-main">
        <header className="admin-header">
          <h1 style={{ fontSize: 18, lineHeight: "28px" }}>{title}</h1>
          <span className="spacer" />
          {actions}
          <button className="btn btn-sm" onClick={logout}>로그아웃</button>
        </header>
        <main className="admin-content" id="admin-main">{children}</main>
      </div>
    </div>
  );
}
