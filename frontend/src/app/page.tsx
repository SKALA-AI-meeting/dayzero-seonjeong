import Link from "next/link";

export default function Home() {
  return (
    <main className="center-wrap">
      <div className="card center-card stack">
        <span className="wordmark"><span className="wordmark-dot" aria-hidden="true" />Day Zero</span>
        <h1>AI 동료와 함께 일하는 하루</h1>
        <p className="help">초대 링크로 입장한 지원자는 바로 작업 공간으로 이동합니다. 관리자는 로그인해 초대를 만들 수 있습니다.</p>
        <Link className="btn btn-primary btn-block" href="/admin/login">관리자 로그인</Link>
      </div>
    </main>
  );
}
