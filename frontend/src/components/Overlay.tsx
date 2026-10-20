"use client";
import { useEffect, useRef } from "react";
import { Icon } from "@/components/Icon";

function useFocusTrap(open: boolean, onEscape?: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  // onEscape는 렌더마다 새로 만들어지므로 ref로 보관한다. effect 의존성에 넣으면 입력할 때마다
  // 포커스를 다시 잡아 한글 IME 조합이 끊긴다(자모 분리 입력 버그).
  const escRef = useRef(onEscape);
  escRef.current = onEscape;
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const sel = 'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select, [tabindex]:not([tabindex="-1"])';
    (el?.querySelector<HTMLElement>("[data-autofocus]") ?? el?.querySelector<HTMLElement>("h2") ?? el)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return;
      if (e.key === "Escape" && escRef.current) { e.preventDefault(); escRef.current(); }
      if (e.key !== "Tab" || !el) return;
      const items = Array.from(el.querySelectorAll<HTMLElement>(sel));
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [open]);
  return ref;
}

/** Modal (DESIGN_GUIDE §6.4): focus trap, Escape(닫기 허용 시), aria-modal, sticky footer. */
export function Modal({ open, title, description, size = "md", onClose, footer, children }: {
  open: boolean; title: string; description?: string; size?: "sm" | "md" | "lg";
  onClose?: () => void; footer?: React.ReactNode; children: React.ReactNode;
}) {
  const ref = useFocusTrap(open, onClose);
  if (!open) return null;
  return (
    <div className="backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
      <div ref={ref} className={`modal ${size}`} role="dialog" aria-modal="true" aria-labelledby="modal-title"
        aria-describedby={description ? "modal-desc" : undefined} tabIndex={-1}>
        <div className="modal-head">
          <div className="row"><h2 id="modal-title" tabIndex={-1}>{title}</h2><span className="spacer" />
            {onClose && <button className="btn btn-tertiary btn-icon btn-sm" aria-label="닫기" onClick={onClose}><Icon name="close" /></button>}
          </div>
          {description && <p id="modal-desc" className="help">{description}</p>}
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

/** Drawer (§4.10): 기본은 modal overlay. modal=false면 배경을 막지 않는 참조 패널(다른 영역과 동시 사용). */
export function Drawer({ open, title, badge, kind = "doc", modal = true, onClose, children, footer }: {
  open: boolean; title: string; badge?: React.ReactNode; kind?: "doc" | "side";
  modal?: boolean; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode;
}) {
  const ref = useFocusTrap(open && modal, onClose);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open || modal) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !e.isComposing) closeRef.current(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, modal]);
  if (!open) return null;
  return (
    <>
      {modal && <div className="backdrop drawer-backdrop" onMouseDown={onClose} />}
      <aside ref={ref} className={`drawer ${kind}`} role={modal ? "dialog" : "complementary"} aria-modal={modal ? true : undefined}
        aria-labelledby="drawer-title" tabIndex={-1}>
        <div className="drawer-head">
          <h3 id="drawer-title" tabIndex={-1}>{title}</h3>{badge}<span className="spacer" />
          <button className="btn btn-tertiary btn-icon btn-sm" aria-label="닫기" onClick={onClose}><Icon name="close" /></button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer}
      </aside>
    </>
  );
}
