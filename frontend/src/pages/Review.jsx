import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ChevronRight, RefreshCw, Download, FileJson, FileSpreadsheet, Trash2, MoreHorizontal, Save, Check,
  Building2, ReceiptText, Crosshair, CircleAlert, Undo2, SearchX, ArrowLeft, UploadCloud, PencilLine, Database,
  ChevronLeft, Layers, PanelLeftClose, PanelLeftOpen, ChevronDown
} from 'lucide-react';
import { api, API_BASE_URL, errorMessage, reprocessDocument } from '../api';
import { useToast } from '../components/toastContext';
import StatusBadge from '../components/StatusBadge';
import DepartmentBadge from '../components/DepartmentBadge';
import ConfidenceMeter from '../components/ConfidenceMeter';
import DropdownMenu from '../components/DropdownMenu';
import ConfirmDialog from '../components/ConfirmDialog';
import EmptyState from '../components/EmptyState';
import FileIcon from '../components/FileIcon';
import Viewer from '../components/Viewer';
import LineItems from '../components/LineItems';
import DocumentAssistant from '../features/chatbot/DocumentAssistant';
import { confidenceTone, humanizeError } from '../lib/status';
import { fileKind, formatDateTime, timeAgo } from '../lib/format';
import './review.css';

const SECTIONS = [
  {
    key: 'document_info',
    title: 'Extracted Contract Details',
    icon: ReceiptText,
    fields: [
      { key: 'execution_date', label: 'Execution Date', type: 'date' },
      { key: 'expiry_date', label: 'Expiry Date', type: 'date' },
      { key: 'validity_tenure', label: 'Validity Tenure' },
      { key: 'mrc', label: 'Monthly Recurring Charges (MRC)' },
      { key: 'otc', label: 'One Time Charges (OTC)' },
      { key: 'termination_clause', label: 'Termination Clause', rows: 4 },
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
          {field && !field.manual && (field.value || '').trim() && typeof field.confidence === 'number' && (
            <span className={`flag conf ${tone}`} title="Detection confidence">{Math.round(field.confidence * 100)}%</span>
          )}
          {missing && !field?.manual && (
            <span className="flag missing">Missing</span>
          )}
          {(field?.box || (field?.value && !field.manual)) && (
            <button type="button" className="locate" onClick={onLocate} title="Highlight on page" aria-label={`Show ${def.label} on the page`}>
              <Crosshair size={14} />
            </button>
          )}
        </span>
      </div>
      {def.rows > 1 ? <textarea rows={def.rows} {...common} /> : <input type="text" {...common} />}
    </div>
  );
}

/* ---------------------------------------------------------------- States */

function ProcessingState({ doc }) {
  const pct = doc.progress_pct || 0;
  const msg = doc.progress_msg || 'Processing...';

  return (
    <div className="state-wrap">
      <div className="card state-card rise">
        <div className="scan-art" aria-hidden="true">
          <div className="scan-sheet">
            <i /><i /><i /><i className="short" /><i /><i className="mid" />
          </div>
          <div className="scan-beam" />
        </div>
        <span className="badge badge-info badge-processing"><span className="dot" /> {pct === 100 ? 'Finalizing' : 'Processing'}</span>
        <h2 className="display">Extracting data from {doc.filename}</h2>
        
        <div style={{ width: '100%', maxWidth: '320px', margin: '1.5rem auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '13px' }}>
            <span className="shimmer-text" style={{ fontWeight: 500 }}>{msg}</span>
            <span className="mono" style={{ color: 'var(--text-muted)' }}>{pct}%</span>
          </div>
          <div style={{ height: '6px', background: 'var(--bg-hover)', borderRadius: '100px', overflow: 'hidden' }}>
            <div style={{ 
              height: '100%', 
              background: 'var(--accent)', 
              width: `${pct}%`,
              transition: 'width 0.5s ease-in-out',
              borderRadius: '100px'
            }} />
          </div>
        </div>

        <p>Text PDFs take a few seconds. Scanned pages need OCR, which can take up to a minute per page.
          You can leave this page — we'll let you know when it's ready.</p>
      </div>
    </div>
  );
}

function ErrorState({ doc, onDelete, onUpload, onRetry, retrying }) {
  const err = humanizeError(doc.error);
  const [showTechnical, setShowTechnical] = useState(false);

  return (
    <div className="state-wrap">
      <div className="card state-card rise">
        <div className="state-icon bad"><CircleAlert size={28} /></div>
        <h2 className="display">{err.title}</h2>
        <p style={{ maxWidth: '440px', margin: '0.5rem auto 1rem', color: 'var(--ink-2)', lineHeight: 1.5 }}>
          {err.description}
        </p>

        {err.technical && (
          <div style={{ margin: '0 auto 1.5rem', maxWidth: '440px' }}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              style={{ fontSize: '12px', padding: '2px 8px', color: 'var(--ink-3)' }}
              onClick={() => setShowTechnical((v) => !v)}
            >
              {showTechnical ? 'Hide technical error' : 'View technical error'}
            </button>
            {showTechnical && (
              <pre className="error-detail mono" style={{ marginTop: '8px', maxHeight: '140px', overflowY: 'auto', textAlign: 'left' }}>
                {err.technical}
              </pre>
            )}
          </div>
        )}

        <div className="state-actions" style={{ display: 'flex', gap: '10px', justifyContent: 'center', flexWrap: 'wrap' }}>
          <button className="btn btn-primary" onClick={onRetry} disabled={retrying} title="Retry processing this file">
            <RefreshCw size={16} className={retrying ? 'spin' : ''} />
            <span>{retrying ? 'Retrying...' : 'Retry Processing'}</span>
          </button>
          <button className="btn btn-secondary" onClick={onUpload} title="Upload a different copy of this file">
            <UploadCloud size={16} /> Upload New Copy
          </button>
          <button className="btn btn-ghost danger" onClick={() => onDelete(doc)}>
            <Trash2 size={16} /> Delete
          </button>
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

export default function Review({ docId, doc, loaded, navigate, onDelete, onUpload, onDirtyChange, onChanged, uploads, documents }) {
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
  const [chatOpen, setChatOpen] = useState(false);
  const [isWide, setIsWide] = useState(false);
  const [isFocusMode, setIsFocusMode] = useState(false);

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
    if ((!dirty && edited) || busy) return;
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
  }, [dirty, edited, busy, docId, draft, notify, onChanged]);

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

  const [retrying, setRetrying] = useState(false);
  const handleRetryProcessing = async () => {
    setRetrying(true);
    try {
      await reprocessDocument(docId);
      notify('Queued for complete reprocessing', 'info');
      if (onChanged) onChanged();
    } catch (e) {
      notify(errorMessage(e, 'Retry failed'), 'error');
    } finally {
      setRetrying(false);
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
  const scored = [...allFields.map((f) => f.field), ...rows].filter(
    (x) => x && !x.manual && (x.value || '').trim() && typeof x.confidence === 'number'
  );
  const avg = scored.length ? scored.reduce((a, x) => a + x.confidence, 0) / scored.length : null;

  const focus = (item, label) => item && setActiveBox({ box: item.box, page_num: item.page_num, value: item.value, label });
  const exportUrl = (format) => `${API_BASE_URL}/documents/${docId}/export?format=${format}`;

  const batchTabs = useMemo(() => {
    // 1. If this doc has a persistent batch_id in database:
    if (doc?.batch_id) {
      const savedInBatch = (documents || []).filter((d) => d.batch_id === doc.batch_id);
      const activeUploads = (uploads || []).filter(
        (u) => u.batchId === doc.batch_id && !savedInBatch.some((d) => d.doc_id === u.docId)
      );

      const items = [
        ...savedInBatch.map((d) => ({
          key: d.doc_id,
          docId: d.doc_id,
          name: d.filename,
          status: d.status,
        })),
        ...activeUploads.map((u) => ({
          key: u.key,
          docId: u.docId,
          name: u.name,
          status: u.state === 'uploaded' ? 'processing' : u.state === 'failed' ? 'error' : 'uploading',
        })),
      ];

      return items.length > 1 ? items : null;
    }

    // 2. Fallback to active uploads session
    if (uploads && uploads.length > 1) {
      const isCurrentInUploads = uploads.some((u) => u.docId === docId);
      if (isCurrentInUploads) {
        return uploads.map((u) => {
          const udoc = u.docId ? documents?.find((d) => d.doc_id === u.docId) : null;
          return {
            key: u.key,
            docId: u.docId,
            name: u.name,
            status: udoc?.status || (u.state === 'uploaded' ? 'processing' : u.state === 'failed' ? 'error' : 'uploading'),
          };
        });
      }
    }

    return null;
  }, [doc?.batch_id, docId, documents, uploads]);

  const currentIndex = useMemo(() => {
    if (!batchTabs) return -1;
    return batchTabs.findIndex((t) => t.docId === docId);
  }, [batchTabs, docId]);

  const prevDocId = currentIndex > 0 ? batchTabs[currentIndex - 1]?.docId : null;
  const nextDocId = currentIndex >= 0 && currentIndex < batchTabs.length - 1 ? batchTabs[currentIndex + 1]?.docId : null;

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
      <div className="review-nav-bar">
        <nav className="crumbs" aria-label="Breadcrumb">
          <a href="#/documents">Documents</a>
          {batchTabs && (
            <>
              <ChevronRight size={14} />
              <a
                href="#/documents?view=batches"
                className="crumb-batch-link"
                title="Return to Batches view"
              >
                <Layers size={13} style={{ marginRight: '4px' }} /> Batches
              </a>
            </>
          )}
          <ChevronRight size={14} />
          <span title={doc.filename}>{doc.filename}</span>
        </nav>

        {batchTabs && (
          <div className="batch-navigator">
            <button
              className="btn btn-ghost btn-sm btn-nav-step"
              disabled={!prevDocId}
              onClick={() => prevDocId && navigate(`/documents/${prevDocId}`)}
              title={prevDocId ? "Previous document in batch" : "First document"}
            >
              <ChevronLeft size={14} /> Prev
            </button>

            <DropdownMenu
              trigger={({ toggle, open }) => (
                <button
                  type="button"
                  className={`btn-batch-counter ${open ? 'open' : ''}`}
                  onClick={toggle}
                  aria-expanded={open}
                  title="Click to jump to another document in this batch"
                >
                  <span>{currentIndex >= 0 ? `${currentIndex + 1} of ${batchTabs.length}` : 'Batch files'}</span>
                  <ChevronDown size={12} className="counter-arrow" />
                </button>
              )}
            >
              {(close) => (
                <div className="batch-jump-menu">
                  <div className="batch-jump-header">Files in batch ({batchTabs.length})</div>
                  <div className="batch-jump-list">
                    {batchTabs.map((u, idx) => {
                      const isCurrent = u.docId === docId;
                      const isReady = u.status === 'completed';
                      const isProcessing = u.status === 'processing' || u.status === 'uploading' || u.status === 'queued';
                      const hasError = u.status === 'error';

                      return (
                        <button
                          key={u.key || u.docId || idx}
                          type="button"
                          className={`batch-jump-item ${isCurrent ? 'active' : ''}`}
                          disabled={!u.docId}
                          onClick={() => {
                            close();
                            if (u.docId && u.docId !== docId) {
                              navigate(`/documents/${u.docId}`);
                            }
                          }}
                        >
                          <span className="jump-index">{idx + 1}.</span>
                          <span className="jump-name" title={u.name}>{u.name}</span>
                          {isReady && <Check size={13} className="jump-status ready" />}
                          {isProcessing && <RefreshCw size={12} className="spin jump-status processing" />}
                          {hasError && <CircleAlert size={13} className="jump-status error" />}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </DropdownMenu>

            <button
              className="btn btn-ghost btn-sm btn-nav-step"
              disabled={!nextDocId}
              onClick={() => nextDocId && navigate(`/documents/${nextDocId}`)}
              title={nextDocId ? "Next document in batch" : "Last document"}
            >
              Next <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>

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
            <DepartmentBadge
              department={doc.department || 'General'}
              interactive={false}
            />
            {(doc.progress_msg === 'Loaded from cache!' || doc.progress_msg?.toLowerCase().includes('smart match')) && (
              <span className="badge badge-smart-match" title="This document was previously analyzed and matched instantly">
                <Database size={12} /> Smart Match
              </span>
            )}
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
            <>
              {chatOpen && (
                <button
                  type="button"
                  className={`btn ${isFocusMode ? 'btn-secondary' : 'btn-ghost'}`}
                  onClick={() => setIsFocusMode((f) => !f)}
                  title={isFocusMode ? 'Exit Focus Mode (Show Extracted Fields)' : 'Focus Mode (Hide fields to maximize PDF & AI Assistant)'}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                >
                  {isFocusMode ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
                  <span>{isFocusMode ? 'Show Fields' : 'Focus Mode'}</span>
                </button>
              )}
              <button
                type="button"
                className={`btn ${chatOpen ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => {
                  setChatOpen((v) => {
                    const next = !v;
                    if (!next) setIsFocusMode(false);
                    return next;
                  });
                }}
                title="Toggle SmartAssistant"
                aria-expanded={chatOpen}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}
              >
                <span className="assistant-brand-mark xs" aria-hidden="true">
                  <span />
                  <span />
                  <span className="hl" />
                </span>
                <span>SmartAssistant</span>
              </button>
            </>
          )}
          {completed && (
            <button className={`btn ${!edited || dirty ? 'btn-primary' : ''}`} onClick={save} disabled={(!dirty && edited) || busy}>
              {dirty ? <Save size={16} /> : (!edited ? <Check size={16} /> : <Save size={16} />)}
              {dirty ? ' Save changes' : (!edited ? ' Approve' : ' Saved')}
            </button>
          )}
        </div>
      </div>
    </header>
  );

  if (doc.status === 'processing') return <div className="page page-review">{header}<ProcessingState doc={doc} /></div>;
  if (doc.status === 'error') return (
    <div className="page page-review">
      {header}
      <ErrorState
        doc={doc}
        onDelete={onDelete}
        onUpload={onUpload}
        onRetry={handleRetryProcessing}
        retrying={retrying}
      />
    </div>
  );
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

      <div className={`workspace ${chatOpen ? 'has-chat' : ''} ${isWide ? 'is-wide' : ''} ${isFocusMode ? 'focus-mode' : ''}`}>
        <div className="fields-pane">
          {/* Summary */}
          <section className="card review-summary rise">
            <div className="rs-stat">
              <span className="rs-label">Completeness</span>
              <span className="rs-value display">
                {Math.round((found / Math.max(1, allFields.length)) * 100)}%
                <small style={{ fontSize: '0.75rem', fontWeight: 500, marginLeft: '6px', opacity: 0.8 }}>({found}/{allFields.length})</small>
              </span>
              <span className="rs-bar"><span style={{ width: `${(found / Math.max(1, allFields.length)) * 100}%` }} /></span>
            </div>
            <div className="rs-stat">
              <span className="rs-label">Action Required</span>
              <span className={`rs-value display ${toCheck ? 'warn' : 'ok'}`}>{toCheck}</span>
              <span className="rs-note">{lowFields + lowRows} low confidence · {allFields.length - found} missing</span>
            </div>
            <div className="rs-stat">
              <span className="rs-label" title="Average confidence score on extracted values">Field Confidence</span>
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

        {chatOpen && (
          <DocumentAssistant
            doc={doc}
            documentTitle={draft?.contract_name?.value || doc.summary?.title || doc.filename}
            open={chatOpen}
            onClose={() => {
              setChatOpen(false);
              setIsFocusMode(false);
            }}
            onJumpToPage={(pageNum) => {
              setActiveBox({ page_num: pageNum });
            }}
            currentPage={activeBox?.page_num || 1}
            isWide={isWide}
            onToggleWide={() => setIsWide((w) => !w)}
            isFocusMode={isFocusMode}
            onToggleFocus={() => setIsFocusMode((f) => !f)}
          />
        )}
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
