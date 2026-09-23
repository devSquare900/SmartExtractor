import { useEffect, useMemo, useRef, useState } from 'react';
import { Search, Upload, MoreHorizontal, ArrowUpRight, Download, FileJson, FileSpreadsheet, Trash2, SearchX, X } from 'lucide-react';
import PageHeader from '../components/PageHeader';
import StatusBadge from '../components/StatusBadge';
import ConfidenceMeter from '../components/ConfidenceMeter';
import FileIcon from '../components/FileIcon';
import DropdownMenu from '../components/DropdownMenu';
import EmptyState from '../components/EmptyState';
import UploadDropzone from '../components/UploadDropzone';
import { displayStatus } from '../lib/status';
import { formatDocDate, formatMoney, timeAgo, formatDateTime } from '../lib/format';
import { API_BASE_URL } from '../api';
import './documents.css';

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'ready', label: 'Ready' },
  { key: 'review', label: 'Needs review' },
  { key: 'processing', label: 'Processing' },
  { key: 'error', label: 'Failed' },
];

const SORTS = {
  newest: { label: 'Newest first', fn: (a, b) => b.created_at.localeCompare(a.created_at) },
  oldest: { label: 'Oldest first', fn: (a, b) => a.created_at.localeCompare(b.created_at) },
  amount: { label: 'Highest amount', fn: (a, b) => (Number(b.summary?.amount) || -1) - (Number(a.summary?.amount) || -1) },
  confidence: { label: 'Lowest confidence', fn: (a, b) => (a.summary?.avg_confidence ?? 2) - (b.summary?.avg_confidence ?? 2) },
  name: { label: 'Name A–Z', fn: (a, b) => a.filename.localeCompare(b.filename) },
};

function RowMenu({ doc, onOpen, onDelete }) {
  const exportUrl = (format) => `${API_BASE_URL}/documents/${doc.doc_id}/export?format=${format}`;
  const ready = doc.status === 'completed';
  return (
    <DropdownMenu
      label={`Actions for ${doc.filename}`}
      trigger={({ toggle, open, label }) => (
        <button className={`btn btn-ghost btn-sm btn-icon row-menu ${open ? 'open' : ''}`} onClick={toggle} aria-label={label} aria-expanded={open}>
          <MoreHorizontal size={17} />
        </button>
      )}
    >
      {(close) => (
        <>
          <button className="menu-item" onClick={() => { close(); onOpen(); }}><ArrowUpRight size={16} /> Open</button>
          <a className="menu-item" href={`${API_BASE_URL}/documents/${doc.doc_id}/file`} download onClick={close}>
            <Download size={16} /> Download original
          </a>
          {ready && (
            <>
              <a className="menu-item" href={exportUrl('json')} download onClick={close}><FileJson size={16} /> Export JSON</a>
              <a className="menu-item" href={exportUrl('csv')} download onClick={close}><FileSpreadsheet size={16} /> Export CSV</a>
            </>
          )}
          <div className="menu-sep" />
          <button className="menu-item danger" onClick={() => { close(); onDelete(doc); }}><Trash2 size={16} /> Delete</button>
        </>
      )}
    </DropdownMenu>
  );
}

export default function Documents({ documents, loaded, navigate, onUpload, onFiles, onDelete, query }) {
  const status = FILTERS.some((f) => f.key === query.status) ? query.status : 'all';
  const [search, setSearch] = useState('');
  const [fromDate, setFromDate] = useState('');
  const [sort, setSort] = useState('newest');
  const searchRef = useRef(null);

  // "/" focuses search
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const counts = useMemo(() => {
    const c = { all: documents.length, ready: 0, review: 0, processing: 0, error: 0 };
    documents.forEach((d) => { c[displayStatus(d)] += 1; });
    return c;
  }, [documents]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return documents
      .filter((d) => status === 'all' || displayStatus(d) === status)
      .filter((d) => !fromDate || d.created_at.slice(0, 10) >= fromDate)
      .filter((d) => {
        if (!q) return true;
        const s = d.summary || {};
        return [d.filename, s.customer, s.title, s.amount_raw].some((v) => v && String(v).toLowerCase().includes(q));
      })
      .sort(SORTS[sort].fn);
  }, [documents, status, fromDate, search, sort]);

  const setStatus = (key) => navigate(key === 'all' ? '/documents' : `/documents?status=${key}`);
  const hasFilters = search || fromDate || status !== 'all';
  const clearFilters = () => { setSearch(''); setFromDate(''); setStatus('all'); };

  const title = { all: 'Documents', ready: 'Ready to use', review: 'Needs review', processing: 'Processing', error: 'Failed' }[status];
  const subtitle = {
    all: 'Everything you have uploaded, newest first.',
    ready: 'Extracted and checked — safe to export.',
    review: 'These have low-confidence values. Open one to confirm or correct them.',
    processing: 'Being read right now. This page updates automatically.',
    error: 'These files could not be processed. Try uploading them again.',
  }[status];

  return (
    <div className="page">
      <PageHeader
        eyebrow="Library"
        title={title}
        subtitle={subtitle}
        actions={<button className="btn btn-primary" onClick={onUpload}><Upload size={16} /> Upload</button>}
      />

      <div className="toolbar card rise">
        <div className="segmented" role="group" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button key={f.key} aria-pressed={status === f.key} onClick={() => setStatus(f.key)}>
              {f.label}
              <span className="count">{counts[f.key]}</span>
            </button>
          ))}
        </div>
        <div className="toolbar-right">
          <label className="search">
            <Search size={16} />
            <span className="sr-only">Search documents</span>
            <input
              ref={searchRef}
              className="input"
              placeholder="Search file, customer, amount…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {!search && <kbd>/</kbd>}
          </label>
          <label className="date-field" title="Uploaded on or after">
            <span className="sr-only">Uploaded from</span>
            <input type="date" className="input" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
          </label>
          <label>
            <span className="sr-only">Sort</span>
            <select className="input" value={sort} onChange={(e) => setSort(e.target.value)}>
              {Object.entries(SORTS).map(([key, s]) => <option key={key} value={key}>{s.label}</option>)}
            </select>
          </label>
          {hasFilters && (
            <button className="btn btn-ghost btn-sm" onClick={clearFilters}><X size={14} /> Clear</button>
          )}
        </div>
      </div>

      <section className="card table-card rise" style={{ '--i': 1 }}>
        {!loaded ? (
          <div className="table-skeleton">
            {Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton" style={{ height: 44 }} />)}
          </div>
        ) : !documents.length ? (
          <div className="table-empty">
            <UploadDropzone onBrowse={onUpload} onFiles={onFiles} />
          </div>
        ) : !rows.length ? (
          <EmptyState
            icon={<SearchX size={26} />}
            title="Nothing matches"
            action={hasFilters && <button className="btn btn-secondary" onClick={clearFilters}>Clear filters</button>}
          >
            {status === 'review' && !search ? 'No documents need review. Everything has been checked.' : 'Try a different search or filter.'}
          </EmptyState>
        ) : (
          <div className="table-scroll">
            <table className="doc-table">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Customer</th>
                  <th>Doc. date</th>
                  <th className="num">Amount</th>
                  <th>Confidence</th>
                  <th>Status</th>
                  <th>Uploaded</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((doc) => {
                  const s = doc.summary || {};
                  const open = () => navigate(`/documents/${doc.doc_id}`);
                  return (
                    <tr key={doc.doc_id} onClick={open} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && open()}>
                      <td>
                        <div className="doc-cell">
                          <FileIcon filename={doc.filename} size={36} />
                          <div>
                            <div className="doc-name" title={doc.filename}>{doc.filename}</div>
                            <div className="doc-sub">
                              {doc.status === 'error' ? <span className="bad-text">{doc.error}</span> : (s.title || '—')}
                              {s.pages ? <span className="dot-sep">{s.pages} page{s.pages > 1 ? 's' : ''}</span> : null}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="ellipsis">{s.customer || <span className="muted">—</span>}</td>
                      <td className="nowrap">{formatDocDate(s.date) || <span className="muted">—</span>}</td>
                      <td className="num mono nowrap">{formatMoney(s.amount, s.currency) || <span className="muted">—</span>}</td>
                      <td>{doc.status === 'completed' ? <ConfidenceMeter value={s.avg_confidence} /> : <span className="muted">—</span>}</td>
                      <td><StatusBadge doc={doc} /></td>
                      <td className="nowrap muted" title={formatDateTime(doc.created_at)}>{timeAgo(doc.created_at)}</td>
                      <td className="actions-cell"><RowMenu doc={doc} onOpen={open} onDelete={onDelete} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {loaded && rows.length > 0 && (
        <p className="table-foot muted">
          Showing {rows.length} of {documents.length} · Press <kbd>/</kbd> to search
        </p>
      )}
    </div>
  );
}
