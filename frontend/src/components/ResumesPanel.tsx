import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { api, ApiError } from '../api';
import type { Resume } from '../types';
import { ConfirmModal } from './ConfirmModal';

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

// Demographic labels for counterfactual bias pairing (the bias probe swaps names
// across these axes using the resumes you label here).
const GENDERS = ['unspecified', 'male', 'female'];
const ETHNICITIES = ['unspecified', 'american', 'african', 'asian', 'hispanic'];
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

// The list is shown alphabetically by applicant name (case-insensitive), regardless of
// when each resume was last edited.
const byName = (a: Resume, b: Resume) =>
  a.applicant_name.localeCompare(b.applicant_name, undefined, { sensitivity: 'base' });

export function ResumesPanel({ onDirtyChange }: { onDirtyChange?: (dirty: boolean) => void }) {
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [text, setText] = useState('');
  const [gender, setGender] = useState('unspecified');
  const [ethnicity, setEthnicity] = useState('unspecified');

  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  // Guards setState in async callbacks if the user switches tabs mid-request.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      onDirtyChange?.(false); // clear the parent's dirty flag on unmount
    };
  }, [onDirtyChange]);

  const selected = useMemo(
    () => resumes.find((r) => r.id === selectedId) ?? null,
    [resumes, selectedId],
  );

  const load = (selectAfter?: string) => {
    setLoading(true);
    setLoadError(null);
    api
      .resumes()
      .then((raw) => {
        if (!mounted.current) return;
        const rs = [...raw].sort(byName);
        setResumes(rs);
        setSelectedId((cur) => {
          const want = selectAfter ?? cur;
          if (want && rs.some((r) => r.id === want)) return want;
          return rs[0]?.id ?? null;
        });
      })
      .catch((e: unknown) => {
        if (mounted.current) setLoadError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Populate the editor whenever the selected resume changes (a fresh draft is set
  // explicitly via newDraft()/PDF extract, which leave selected === null).
  useEffect(() => {
    if (selected) {
      setName(selected.applicant_name);
      setText(selected.resume_text);
      setGender(selected.gender ?? 'unspecified');
      setEthnicity(selected.ethnicity ?? 'unspecified');
    }
  }, [selected]);

  const dirty = selected
    ? name !== selected.applicant_name ||
      text !== selected.resume_text ||
      gender !== selected.gender ||
      ethnicity !== selected.ethnicity
    : name.trim() !== '' ||
      text.trim() !== '' ||
      gender !== 'unspecified' ||
      ethnicity !== 'unspecified';
  const canSave = dirty && name.trim() !== '' && text.trim() !== '' && !saving;

  // Report unsaved-changes state up so the app can warn before navigating away.
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  const newDraft = () => {
    setActionError(null);
    setSelectedId(null);
    setName('');
    setText('');
    setGender('unspecified');
    setEthnicity('unspecified');
  };

  const save = () => {
    if (!name.trim() || !text.trim()) return;
    setSaving(true);
    setActionError(null);
    const req = selectedId
      ? api.updateResume(selectedId, name.trim(), text.trim(), gender, ethnicity)
      : api.createResume(name.trim(), text.trim(), gender, ethnicity);
    req
      .then((saved) => {
        if (mounted.current) load(saved.id);
      })
      .catch((e: unknown) => {
        if (mounted.current) setActionError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => {
        if (mounted.current) setSaving(false);
      });
  };

  const doDelete = () => {
    if (!selectedId) return;
    setDeleting(true);
    setActionError(null);
    api
      .deleteResume(selectedId)
      .then(() => {
        if (!mounted.current) return;
        setConfirmDelete(false);
        setName('');
        setText('');
        setGender('unspecified');
        setEthnicity('unspecified');
        load(); // auto-selects the first remaining resume
      })
      .catch((e: unknown) => {
        if (mounted.current) setActionError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => {
        if (mounted.current) setDeleting(false);
      });
  };

  const doReset = () => {
    setResetting(true);
    setActionError(null);
    api
      .resetResumes()
      .then((raw) => {
        if (!mounted.current) return;
        const rs = [...raw].sort(byName);
        setConfirmReset(false);
        setResumes(rs);
        setSelectedId(rs[0]?.id ?? null); // discards any draft; editor repopulates from selection
      })
      .catch((e: unknown) => {
        if (mounted.current) setActionError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => {
        if (mounted.current) setResetting(false);
      });
  };

  const onPickPdf = () => fileRef.current?.click();
  const onPdfChosen = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // let the same file be re-selected later
    if (!file) return;
    setExtracting(true);
    setActionError(null);
    api
      .extractResumePdf(file)
      .then((res) => {
        if (!mounted.current) return;
        // start a fresh draft pre-filled with the extracted text + a suggested name
        setSelectedId(null);
        setName(file.name.replace(/\.pdf$/i, ''));
        setText(res.text);
        setGender('unspecified');
        setEthnicity('unspecified');
      })
      .catch((err: unknown) => {
        if (mounted.current) setActionError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (mounted.current) setExtracting(false);
      });
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Sample resumes</h2>
        <span className="count">
          {resumes.length} resume{resumes.length === 1 ? '' : 's'}
        </span>
      </div>
      <p className="hint">
        These resumes are the clean corpus every assessment probes against — edit them to change what
        the application is tested with. Probes append adversarial text and swap applicant names at run
        time; your edits take effect on the next run.
      </p>

      {loadError && (
        <div className="error" role="alert" aria-live="polite">
          ⚠ {loadError}
        </div>
      )}

      <div className="resumes-layout">
        <aside className="resume-list">
          <div className="resume-list-actions">
            <button className="btn" onClick={newDraft}>
              + New
            </button>
            <button className="btn" onClick={onPickPdf} disabled={extracting}>
              {extracting ? 'Extracting…' : 'Extract from PDF'}
            </button>
            <button
              className="btn danger-ghost"
              onClick={() => {
                setActionError(null);
                setConfirmReset(true);
              }}
              disabled={resetting}
              title="Delete all resumes and restore the shipped defaults"
            >
              Reset all
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf,.pdf"
              hidden
              onChange={onPdfChosen}
            />
          </div>
          {loading && resumes.length === 0 ? (
            <p className="empty">Loading…</p>
          ) : resumes.length === 0 ? (
            <p className="empty">No resumes — create one or extract from a PDF.</p>
          ) : (
            <ul className="resume-items">
              {resumes.map((r) => (
                <li key={r.id}>
                  <button
                    className={`resume-item${selectedId === r.id ? ' active' : ''}`}
                    onClick={() => {
                      setActionError(null);
                      setSelectedId(r.id);
                    }}
                  >
                    <strong>{r.applicant_name}</strong>
                    {[r.gender, r.ethnicity].some((v) => v && v !== 'unspecified') && (
                      <span className="resume-tags">
                        {[r.gender, r.ethnicity]
                          .filter((v) => v && v !== 'unspecified')
                          .map(cap)
                          .join(' · ')}
                      </span>
                    )}
                    <span className="resume-meta">updated {fmtTime(r.updated_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <div className="resume-editor">
          <div className="resume-editor-head">
            <h3>{selectedId ? 'Edit resume' : 'New resume'}</h3>
            {dirty && <span className="dirty-flag">● unsaved changes</span>}
          </div>
          {actionError && (
            <div className="error" role="alert" aria-live="polite">
              ⚠ {actionError}
            </div>
          )}
          <label className="field">
            <span>Applicant name</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. James Carter"
              required
              aria-required="true"
            />
          </label>
          <div className="field-row">
            <label className="field">
              <span>Gender</span>
              <select value={gender} onChange={(e) => setGender(e.target.value)}>
                {GENDERS.map((g) => (
                  <option key={g} value={g}>
                    {cap(g)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Cultural background</span>
              <select value={ethnicity} onChange={(e) => setEthnicity(e.target.value)}>
                {ETHNICITIES.map((x) => (
                  <option key={x} value={x}>
                    {cap(x)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="field-hint">
            Used to pair names across the gender and cultural-background axes when testing for bias.
          </p>
          <label className="field">
            <span>Resume text</span>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={12}
              placeholder="Paste or type the resume text, or use “Extract from PDF”."
              required
              aria-required="true"
            />
          </label>
          <div className="editor-actions">
            <button className="btn primary" onClick={save} disabled={!canSave}>
              {saving ? 'Saving…' : selectedId ? 'Save changes' : 'Create resume'}
            </button>
            {selectedId && (
              <button
                className="btn danger-ghost"
                onClick={() => {
                  setActionError(null);
                  setConfirmDelete(true);
                }}
                disabled={deleting}
              >
                Delete
              </button>
            )}
          </div>
        </div>
      </div>

      {confirmDelete && selected && (
        <ConfirmModal
          title={`Delete resume “${selected.applicant_name}”?`}
          confirmLabel={deleting ? 'Deleting…' : 'Delete permanently'}
          danger
          busy={deleting}
          error={actionError}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={doDelete}
        >
          This permanently removes this sample resume from the corpus. This cannot be undone.
        </ConfirmModal>
      )}

      {confirmReset && (
        <ConfirmModal
          title="Reset all resumes?"
          confirmLabel={resetting ? 'Resetting…' : 'Reset to defaults'}
          danger
          busy={resetting}
          error={actionError}
          onCancel={() => setConfirmReset(false)}
          onConfirm={doReset}
        >
          This permanently deletes <strong>all resumes</strong> and any modifications you have made,
          and replaces them with the application’s initial default configuration. This cannot be undone.
        </ConfirmModal>
      )}
    </section>
  );
}
