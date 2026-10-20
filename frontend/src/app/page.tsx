import Link from "next/link";

export default function Home() {
  return (
    <main className="center-card card stack">
      <h1><span className="brand-dot" />Day Zero</h1>
      <p className="muted">초대 링크로 입장한 지원자는 바로 작업 공간으로 이동합니다. 관리자는 로그인해 초대를 만들 수 있습니다.</p>
      <Link className="btn btn-primary" href="/admin/login">관리자 로그인</Link>
    </main>
  );
}
