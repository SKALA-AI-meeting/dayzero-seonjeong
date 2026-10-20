"use client";
import { useEffect, useRef } from "react";
import { Icon } from "@/components/Icon";

function useFocusTrap(open: boolean, onEscape?: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const sel = 'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select, [tabindex]:not([tabindex="-1"])';
    (el?.querySelector<HTMLElement>("[data-autofocus]") ?? el?.querySelector<HTMLElement>("h2") ?? el)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && onEscape) { e.preventDefault(); onEscape(); }
      if (e.key !== "Tab" || !el) return;
      const items = Array.from(el.querySelectorAll<HTMLElement>(sel));
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [open, onEscape]);
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

/** Drawer (§4.10, §4.11): 우측 overlay, Escape로 닫기. */
export function Drawer({ open, title, badge, kind = "doc", onClose, children, footer }: {
  open: boolean; title: string; badge?: React.ReactNode; kind?: "doc" | "assistant";
  onClose: () => void; children: React.ReactNode; footer?: React.ReactNode;
}) {
  const ref = useFocusTrap(open, onClose);
  if (!open) return null;
  return (
    <>
      <div className="backdrop drawer-backdrop" onMouseDown={onClose} />
      <aside ref={ref} className={`drawer ${kind === "assistant" ? "assistant" : ""}`} role="dialog" aria-modal="true" aria-labelledby="drawer-title" tabIndex={-1}>
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
