/** 단색 선형 아이콘(외부 의존 없음). 상태는 아이콘 형태 + 텍스트로 함께 전달한다(DESIGN_GUIDE §9.5). */
const PATHS: Record<string, string> = {
  check: "M4 10.5l3.5 3.5L16 6",
  warning: "M10 3l8 14H2L10 3zm0 5v4m0 3h.01",
  error: "M10 18a8 8 0 100-16 8 8 0 000 16zM7 7l6 6m0-6l-6 6",
  info: "M10 18a8 8 0 100-16 8 8 0 000 16zm0-9v5m0-8h.01",
  lock: "M5 9h10v8H5zM7 9V6a3 3 0 016 0v3",
  hash: "M7 3L5 17M15 3l-2 14M3 7h14M3 13h14",
  doc: "M5 2h7l4 4v12H5zM12 2v4h4M8 10h5M8 13h5",
  task: "M4 5h12M4 10h12M4 15h8",
  sparkle: "M10 2l1.8 4.6L16 8l-4.2 1.4L10 14l-1.8-4.6L4 8l4.2-1.4L10 2zM15 13l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2z",
  send: "M3 10l14-7-5 14-2-6-7-1z",
  close: "M5 5l10 10M15 5L5 15",
  brief: "M3 6h14v10H3zM7 6V4h6v2",
  menu: "M3 5h14M3 10h14M3 15h14",
  edit: "M4 16l1-4 8-8 3 3-8 8-4 1z",
  clock: "M10 18a8 8 0 100-16 8 8 0 000 16zm0-12v4l3 2",
};

export function Icon({ name, label, className = "icon" }: { name: keyof typeof PATHS | string; label?: string; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round"
      strokeLinejoin="round" role={label ? "img" : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <path d={PATHS[name] ?? PATHS.info} />
    </svg>
  );
}
