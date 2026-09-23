import { useState } from 'react';
import { ChevronDown, X, AlertCircle, ArrowUpRight } from 'lucide-react';
import FileIcon from './FileIcon';
import { displayStatus } from '../lib/status';

// Bottom-right panel following each upload from transfer through processing.
export default function UploadTray({ uploads, documents, onOpen, onClear }) {
  const [collapsed, setCollapsed] = useState(false);
  if (!uploads.length) return null;

  const byId = Object.fromEntries(documents.map((d) => [d.doc_id, d]));
  const rows = uploads.map((u) => {
    const doc = u.docId ? byId[u.docId] : null;
    let phase = u.state;
    if (u.state === 'uploaded') {
      const s = displayStatus(doc);
      phase = s === 'processing' ? 'processing' : s === 'error' ? 'failed' : 'done';
    }
    return { ...u, doc, phase };
  });
  const active = rows.filter((r) => r.phase === 'uploading' || r.phase === 'processing').length;
  const done = rows.filter((r) => r.phase === 'done').length;

  return (
    <section className={`upload-tray ${collapsed ? 'collapsed' : ''}`} aria-label="Uploads">
      <header>
        <div>
          <strong>{active ? `Processing ${active} file${active > 1 ? 's' : ''}` : 'Uploads complete'}</strong>
          <span>{done} of {rows.length} ready</span>
        </div>
        <button className="btn btn-ghost btn-sm btn-icon" onClick={() => setCollapsed((c) => !c)} aria-label={collapsed ? 'Expand' : 'Collapse'}>
          <ChevronDown size={16} style={{ transform: collapsed ? 'rotate(180deg)' : undefined }} />
        </button>
        {!active && (
          <button className="btn btn-ghost btn-sm btn-icon" onClick={onClear} aria-label="Close uploads">
            <X size={16} />
          </button>
        )}
      </header>
      {!collapsed && (
        <ul>
          {rows.map((r) => (
            <li key={r.key}>
              <FileIcon filename={r.name} size={30} />
              <div className="tray-body">
                <span className="tray-name" title={r.name}>{r.name}</span>
                {r.phase === 'uploading' && (
                  <span className="tray-progress"><span style={{ width: `${r.progress}%` }} /></span>
                )}
                {r.phase === 'processing' && <span className="tray-meta shimmer-text">Reading pages…</span>}
                {r.phase === 'done' && <span className="tray-meta ok">Ready to review</span>}
                {r.phase === 'failed' && <span className="tray-meta bad">{r.error || r.doc?.error || 'Failed'}</span>}
              </div>
              {r.phase === 'uploading' && <span className="tray-pct mono">{r.progress}%</span>}
              {r.phase === 'done' && (
                <button className="btn btn-secondary btn-sm" onClick={() => onOpen(r.docId)}>
                  Open <ArrowUpRight size={14} />
                </button>
              )}
              {r.phase === 'failed' && <AlertCircle size={18} className="tray-state bad" />}
              {r.phase === 'processing' && <span className="spinner" aria-label="Processing" />}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
