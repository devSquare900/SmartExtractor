import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ChevronRight, RefreshCw, Download, FileJson, FileSpreadsheet, Trash2, MoreHorizontal, Save,
  Building2, ReceiptText, Crosshair, CircleAlert, Undo2, SearchX, ArrowLeft, UploadCloud, PencilLine,
} from 'lucide-react';
import { api, API_BASE_URL, errorMessage } from '../api';
import { useToast } from '../components/toastContext';
import StatusBadge from '../components/StatusBadge';
import ConfidenceMeter from '../components/ConfidenceMeter';
import DropdownMenu from '../components/DropdownMenu';
import ConfirmDialog from '../components/ConfirmDialog';
import EmptyState from '../components/EmptyState';
import FileIcon from '../components/FileIcon';
import Viewer from '../components/Viewer';
import LineItems from '../components/LineItems';
import { confidenceTone } from '../lib/status';
import { fileKind, formatDateTime, timeAgo } from '../lib/format';
import './review.css';

const SECTIONS = [
  {
    key: 'customer_info',
    title: 'Customer',
    icon: Building2,
    fields: [
      { key: 'name', label: 'Customer name', rows: 2 },
      { key: 'email', label: 'Email' },
      { key: 'billing_address', label: 'Billing address', rows: 3 },
      { key: 'poc_contact', label: 'Contact / phone', rows: 2 },
    ],
  },
  {
    key: 'document_info',
    title: 'Document details',
    icon: ReceiptText,
    fields: [
      { key: 'date', label: 'Date', type: 'date' },
      { key: 'doc_number', label: 'Document / invoice no.' },
      { key: 'amount', label: 'Total amount', type: 'amount' },
      { key: 'po_number', label: 'PO number' },
    ],
  },
];

const clone = (value) => JSON.parse(JSON.stringify(value));

const isLow = (item, threshold) =>
  item && !item.manual && typeof item.confidence === 'number' && item.confidence < threshold;

function withValue(field, value) {
  const next = field ? { ...field, value, manual: true } : { value, manual: true };
  delete next.normalized;
  delete next.currency;
  return next;
}

/* ---------------------------------------------------------------- Field */

function FieldRow({ def, field, threshold, onChange, onFocus, onLocate }) {
  const value = field?.value ?? '';
  const low = isLow(field, threshold);
  const missing = !value.trim();
  const tone = field && !field.manual ? confidenceTone(field.confidence, threshold) : '';

  let hint = null;
  if (def.type && value && !field?.manual) {
    if (field?.normalized) {
      const shown = def.type === 'amount' && field.currency ? `${field.currency} ${field.normalized}` : field.normalized;
      if (shown !== value) hint = <span className="field-hint">Standardised as <b className="mono">{shown}</b></span>;
    } else {
      hint = <span className="field-hint warn">Couldn't read this as {def.type === 'date' ? 'a date' : 'an amount'}</span>;
    }
  }

  const common = {
    id: `f-${def.key}`,
    className: 'field-input',
    value,
    placeholder: 'Not found — type to add',
    onChange: (e) => onChange(e.target.value),
    onFocus,
  };

  return (
    <div className={`field ${low ? 'is-low' : ''} ${missing ? 'is-missing' : ''} ${field?.manual ? 'is-edited' : ''}`}>
      <div className="field-top">
        <label htmlFor={common.id}>{def.label}</label>
        <span className="field-flags">
          {field?.manual && <span className="flag edited"><PencilLine size={11} /> Edited</span>}
          {low && <span className="flag low"><CircleAlert size={11} /> Check</span>}
          {field && !field.manual && typeof field.confidence === 'number' && (
            <span className={`flag conf ${tone}`} title="OCR confidence">{Math.round(field.confidence * 100)}%</span>
          )}
          {field?.box && (
            <button type="button" className="locate" onClick={onLocate} title={`Show on page ${field.page_num}`} aria-label={`Show ${def.label} on the page`}>
              <Crosshair size={14} />
            </button>
          )}
        </span>
      </div>
      {def.rows > 1 ? <textarea rows={def.rows} {...common} /> : <input type="text" {...common} />}
      {hint}
    </div>
  );
}

/* ---------------------------------------------------------------- States */

function ProcessingState({ doc }) {
  return (
    <div className="state-wrap">
      <div className="card state-card rise">
        <div className="scan-art" aria-hidden="true">
          <div className="scan-sheet">
            <i /><i /><i /><i className="short" /><i /><i className="mid" />
          </div>
          <div className="scan-beam" />
        </div>
        <span className="badge badge-info badge-processing"><span className="dot" /> Reading pages</span>
        <h2 className="display">Extracting data from {doc.filename}</h2>
        <p>Text PDFs take a few seconds. Scanned pages need OCR, which can take up to a minute per page.
          You can leave this page — we'll let you know when it's ready.</p>
      </div>
    </div>
  );
}

function ErrorState({ doc, onDelete, onUpload }) {
  return (
    <div className="state-wrap">
      <div className="card state-card rise">
        <div className="state-icon bad"><CircleAlert size={26} /></div>
        <h2 className="display">We couldn't process this file</h2>
        <p>The file may be damaged, password-protected, or in a format we can't read.</p>
        <pre className="error-detail mono">{doc.error || 'Unknown error'}</pre>
        <div className="state-actions">
          <button className="btn btn-secondary" onClick={() => onDelete(doc)}><Trash2 size={16} /> Delete</button>
          <button className="btn btn-primary" onClick={onUpload}><UploadCloud size={16} /> Upload again</button>
        </div>
      </div>
    </div>
  );
}

function WorkspaceSkeleton() {
  return (
    <div className="workspace">
      <div className="fields-pane">
        {[160, 320, 260].map((h, i) => <div key={i} className="card skeleton-card"><div className="skeleton" style={{ height: h }} /></div>)}
      </div>
      <div className="viewer-pane"><div className="viewer"><div className="viewer-canvas" /></div></div>
    </div>
  );
}

/* ---------------------------------------------------------------- Page */

export default function Review({ docId, doc, loaded, navigate, onDelete, onUpload, onDirtyChange, onChanged }) {
  const notify = useToast();
  const [draft, setDraft] = useState(null);
  const [saved, setSaved] = useState(null);
  const [edited, setEdited] = useState(false);
  const [threshold, setThreshold] = useState(0.85);
  const [loadError, setLoadError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [activeBox, setActiveBox] = useState(null);
  const [onlyToCheck, setOnlyToCheck] = useState(false);
  const [confirmReextract, setConfirmReextract] = useState(false);

  const completed = doc?.status === 'completed';
  const dirty = useMemo(() => draft !== null && saved !== null && JSON.stringify(draft) !== JSON.stringify(saved), [draft, saved]);

  // Load extracted data once the document is processed.
  useEffect(() => {
    if (!completed) return undefined;
    let cancelled = false;
    api.get(`/documents/${docId}/extracted`)
      .then((r) => {
        if (cancelled) return;
        const data = r.data.data || {};
        setDraft(data);
        setSaved(data);
        setEdited(r.data.edited);
        setThreshold(r.data.low_confidence_threshold ?? 0.85);
      })
      .catch((e) => !cancelled && setLoadError(errorMessage(e, 'Could not load extracted data')));
    return () => { cancelled = true; };
  }, [docId, completed]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  const update = (mutator) => setDraft((current) => {
    const next = clone(current);
    mutator(next);
    return next;
  });

  const save = useCallback(async () => {
    if (!dirty || busy) return;
    setBusy(true);
    try {
      const r = await api.put(`/documents/${docId}/extracted`, draft);
      setDraft(r.data.data);
      setSaved(r.data.data);
      setEdited(true);
      notify('Changes saved', 'success');
      onChanged();
    } catch (e) {
      notify(errorMessage(e, 'Save failed'), 'error');
    } finally {
      setBusy(false);
    }
  }, [dirty, busy, docId, draft, notify, onChanged]);

  // Cmd/Ctrl + S
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        save();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [save]);

  const reextract = async () => {
    setConfirmReextract(false);
    setBusy(true);
    try {
      const r = await api.post(`/documents/${docId}/reextract`);
      setDraft(r.data.data);
      setSaved(r.data.data);
      setEdited(false);
      notify('Extracted again from the original text', 'success');
      onChanged();
    } catch (e) {
      notify(errorMessage(e, 'Re-extract failed'), 'error');
    } finally {
      setBusy(false);
    }
  };

  /* ---------- derived ---------- */

  const allFields = draft
    ? SECTIONS.flatMap((s) => s.fields.map((f) => ({ section: s.key, def: f, field: draft[s.key]?.[f.key] })))
    : [];
  const lineItems = draft?.line_items || { columns: [], rows: [] };
  const rows = lineItems.rows || [];
  const found = allFields.filter((f) => (f.field?.value || '').trim()).length;
  const lowFields = allFields.filter((f) => isLow(f.field, threshold)).length;
  const lowRows = rows.filter((r) => isLow(r, threshold)).length;
  const toCheck = lowFields + lowRows + (allFields.length - found);
  const scored = [...allFields.map((f) => f.field), ...rows].filter((x) => x && !x.manual && typeof x.confidence === 'number');
  const avg = scored.length ? scored.reduce((a, x) => a + x.confidence, 0) / scored.length : null;

  const focus = (item, label) => item?.box && setActiveBox({ box: item.box, page_num: item.page_num, label });
  const exportUrl = (format) => `${API_BASE_URL}/documents/${docId}/export?format=${format}`;

  /* ---------- not found / loading ---------- */

  if (!loaded) return <div className="page page-review"><WorkspaceSkeleton /></div>;
  if (!doc) {
    return (
      <div className="page">
        <EmptyState
          icon={<SearchX size={26} />}
          title="Document not found"
          action={<button className="btn btn-secondary" onClick={() => navigate('/documents')}><ArrowLeft size={16} /> Back to documents</button>}
        >
          It may have been deleted.
        </EmptyState>
      </div>
    );
  }

  const header = (
    <header className="review-header">
      <nav className="crumbs" aria-label="Breadcrumb">
        <a href="#/documents">Documents</a>
        <ChevronRight size={14} />
        <span title={doc.filename}>{doc.filename}</span>
      </nav>

      <div className="review-title-row">
        <FileIcon filename={doc.filename} size={46} />
        <div className="review-title-block">
          {completed && draft ? (
            <input
              className="review-title display"
              value={draft.contract_name?.value ?? ''}
              placeholder="Untitled document"
              onChange={(e) => update((d) => { d.contract_name = withValue(d.contract_name, e.target.value); })}
              onFocus={() => focus(draft.contract_name, 'Title')}
              aria-label="Document title"
            />
          ) : (
            <h1 className="review-title display static">{doc.summary?.title || doc.filename}</h1>
          )}
          <div className="review-meta">
            <StatusBadge doc={doc} />
            {edited && <span className="badge"><PencilLine size={12} /> Edited</span>}
            <span>{fileKind(doc.filename)}</span>
            {doc.summary?.pages ? <span>{doc.summary.pages} page{doc.summary.pages > 1 ? 's' : ''}</span> : null}
            <span title={formatDateTime(doc.created_at)}>Uploaded {timeAgo(doc.created_at)}</span>
          </div>
        </div>

        <div className="review-actions">
          {completed && (
            <>
              <button className="btn btn-ghost" onClick={() => (edited || dirty ? setConfirmReextract(true) : reextract())} disabled={busy}
                title="Run extraction again on this document's text">
                <RefreshCw size={16} className={busy ? 'spin' : ''} /> Re-extract
              </button>
              <DropdownMenu
                trigger={({ toggle, open }) => (
                  <button className="btn btn-secondary" onClick={toggle} aria-expanded={open}>
                    <Download size={16} /> Export
                  </button>
                )}
              >
                {(close) => (
                  <>
                    {dirty && <div className="menu-note">Exports use the last saved version.</div>}
                    <a className="menu-item" href={exportUrl('json')} download onClick={close}><FileJson size={16} /> JSON</a>
                    <a className="menu-item" href={exportUrl('csv')} download onClick={close}><FileSpreadsheet size={16} /> CSV for Excel</a>
                    <div className="menu-sep" />
                    <a className="menu-item" href={`${API_BASE_URL}/documents/${docId}/file`} download onClick={close}><Download size={16} /> Original file</a>
                  </>
                )}
              </DropdownMenu>
            </>
          )}
          <DropdownMenu
            trigger={({ toggle, open }) => (
              <button className="btn btn-ghost btn-icon" onClick={toggle} aria-expanded={open} aria-label="More actions">
                <MoreHorizontal size={18} />
              </button>
            )}
          >
            {(close) => (
              <button className="menu-item danger" onClick={() => { close(); onDelete(doc); }}><Trash2 size={16} /> Delete document</button>
            )}
          </DropdownMenu>
          {completed && (
            <button className="btn btn-primary" onClick={save} disabled={!dirty || busy}>
              <Save size={16} /> {dirty ? 'Save changes' : 'Saved'}
            </button>
          )}
        </div>
      </div>
    </header>
  );

  if (doc.status === 'processing') return <div className="page page-review">{header}<ProcessingState doc={doc} /></div>;
  if (doc.status === 'error') return <div className="page page-review">{header}<ErrorState doc={doc} onDelete={onDelete} onUpload={onUpload} /></div>;
  if (loadError) {
    return (
      <div className="page page-review">
        {header}
        <EmptyState icon={<CircleAlert size={26} />} title="Couldn't load the data">{loadError}</EmptyState>
      </div>
    );
  }
  if (!draft) return <div className="page page-review">{header}<WorkspaceSkeleton /></div>;

  return (
    <div className="page page-review">
      {header}

      <div className="workspace">
        <div className="fields-pane">
          {/* Summary */}
          <section className="card review-summary rise">
            <div className="rs-stat">
              <span className="rs-label">Fields found</span>
              <span className="rs-value display">{found}<small>/{allFields.length}</small></span>
              <span className="rs-bar"><span style={{ width: `${(found / Math.max(1, allFields.length)) * 100}%` }} /></span>
            </div>
            <div className="rs-stat">
              <span className="rs-label">To check</span>
              <span className={`rs-value display ${toCheck ? 'warn' : 'ok'}`}>{toCheck}</span>
              <span className="rs-note">{lowFields + lowRows} low confidence · {allFields.length - found} missing</span>
            </div>
            <div className="rs-stat">
              <span className="rs-label">Confidence</span>
              <span className="rs-value display">{avg == null ? '—' : `${Math.round(avg * 100)}%`}</span>
              <ConfidenceMeter value={avg} threshold={threshold} width={90} />
            </div>
            <label className={`switch ${toCheck ? '' : 'disabled'}`}>
              <input type="checkbox" checked={onlyToCheck} disabled={!toCheck} onChange={(e) => setOnlyToCheck(e.target.checked)} />
              <span className="switch-track"><span /></span>
              Only show what needs checking
            </label>
          </section>

          {/* Field sections */}
          {SECTIONS.map((section, si) => {
            const visible = section.fields.filter((def) => {
              if (!onlyToCheck) return true;
              const field = draft[section.key]?.[def.key];
              return isLow(field, threshold) || !(field?.value || '').trim();
            });
            if (!visible.length) return null;
            const Icon = section.icon;
            return (
              <section key={section.key} className="card field-card rise" style={{ '--i': si + 1 }}>
                <div className="card-head">
                  <h2 className="card-title"><span className="title-icon"><Icon size={16} /></span>{section.title}</h2>
                </div>
                <div className="field-grid">
                  {visible.map((def) => {
                    const field = draft[section.key]?.[def.key];
                    return (
                      <FieldRow
                        key={def.key}
                        def={def}
                        field={field}
                        threshold={threshold}
                        onChange={(value) => update((d) => {
                          d[section.key] = d[section.key] || {};
                          d[section.key][def.key] = withValue(d[section.key][def.key], value);
                        })}
                        onFocus={() => focus(field, def.label)}
                        onLocate={() => focus(field, def.label)}
                      />
                    );
                  })}
                </div>
              </section>
            );
          })}

          {/* Line items */}
          {(!onlyToCheck || lowRows > 0) && (
            <LineItems
              lineItems={lineItems}
              threshold={threshold}
              onlyToCheck={onlyToCheck}
              onChange={update}
              onFocusRow={(row, label) => focus(row, label)}
            />
          )}

          <div className="pane-spacer" />
        </div>

        <div className="viewer-pane">
          <Viewer doc={doc} activeBox={activeBox} threshold={threshold} />
        </div>
      </div>

      {/* Unsaved changes bar */}
      <div className={`save-bar ${dirty ? 'show' : ''}`} role="region" aria-label="Unsaved changes" aria-hidden={!dirty}>
        <span className="save-dot" />
        <span>Unsaved changes</span>
        <kbd>⌘ S</kbd>
        <button className="btn btn-ghost btn-sm" onClick={() => setDraft(saved)} tabIndex={dirty ? 0 : -1}>
          <Undo2 size={14} /> Discard
        </button>
        <button className="btn btn-lime btn-sm" onClick={save} disabled={busy} tabIndex={dirty ? 0 : -1}>
          <Save size={14} /> Save
        </button>
      </div>

      <ConfirmDialog
        open={confirmReextract}
        tone="neutral"
        title="Re-extract this document?"
        body="Extraction runs again on the original text. Your edits to this document will be replaced."
        confirmLabel="Re-extract"
        onConfirm={reextract}
        onCancel={() => setConfirmReextract(false)}
      />
    </div>
  );
}
