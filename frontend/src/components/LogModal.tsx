import { useEffect, useLayoutEffect, useRef } from 'react';

interface Props {
  title: string;
  text: string;
  onClose: () => void;
}

// How close to the bottom (px) still counts as "at the bottom" (rounding/subpixel slack).
const STICK_SLACK = 8;

// A large-screen modal that shows a run's full progress log. It "follows the tail": as new
// lines are appended it keeps the view pinned to the bottom — but only while the user is
// already at the bottom. If they've scrolled up to read, their position is left untouched.
export function LogModal({ title, text, onClose }: Props) {
  const preRef = useRef<HTMLPreElement | null>(null);
  const stick = useRef(true); // start pinned (open showing the latest line)

  const onScroll = () => {
    const el = preRef.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight <= STICK_SLACK;
  };

  // On open and whenever the text grows, jump to the bottom IF we were sticking. Layout
  // effect so the scroll lands before paint (no flicker). Appending text doesn't move
  // scrollTop, so `stick` still reflects the user's pre-append position here. We re-pin on
  // the next frame too, in case a late reflow (modal layout, line wrapping) changed the
  // height after the synchronous pass — the `stick` re-check keeps it from yanking a user
  // who scrolled up in between.
  useLayoutEffect(() => {
    const toBottom = () => {
      const el = preRef.current;
      if (el && stick.current) el.scrollTop = el.scrollHeight;
    };
    toBottom();
    const id = requestAnimationFrame(toBottom);
    return () => cancelAnimationFrame(id);
  }, [text]);

  // If the box resizes while following (window resize / layout settle), keep it pinned.
  // Same `stick` gate, so a user who's scrolled up is never yanked back down.
  useEffect(() => {
    const el = preRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => {
      if (stick.current && preRef.current) preRef.current.scrollTop = preRef.current.scrollHeight;
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="modal modal-wide"
        role="dialog"
        aria-modal="true"
        aria-label={`Full progress log — ${title}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h3>{title} — full progress log</h3>
          <button className="btn ghost" onClick={onClose} aria-label="Close full log">
            ✕
          </button>
        </div>
        <pre className="run-log run-log-full" ref={preRef} onScroll={onScroll}>
          {text}
        </pre>
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
