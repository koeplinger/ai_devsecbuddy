import { useEffect } from 'react';

interface Props {
  title: string;
  text: string;
  onClose: () => void;
}

// A large-screen modal that shows a run's full progress log (the inline box is fixed-height
// and scrolls; this is the "read it all" view). Closes on Escape or click outside.
export function LogModal({ title, text, onClose }: Props) {
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
        <pre className="run-log run-log-full">{text}</pre>
        <div className="modal-actions">
          <button className="btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
