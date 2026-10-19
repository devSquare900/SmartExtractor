import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Search, MoreHorizontal, ArrowUpRight, Download, FileJson, FileSpreadsheet, Trash2, SearchX, X,
  CheckSquare, Square, Layers, FileText, ChevronDown, ChevronRight, Check, RefreshCw, CircleAlert, Folder, FolderPlus
} from 'lucide-react';
import PageHeader from '../components/PageHeader';
import StatusBadge from '../components/StatusBadge';
import ConfidenceMeter from '../components/ConfidenceMeter';
import FileIcon from '../components/FileIcon';
import DropdownMenu from '../components/DropdownMenu';
import EmptyState from '../components/EmptyState';
import UploadDropzone from '../components/UploadDropzone';
import DepartmentBadge, { getDepartmentTheme } from '../components/DepartmentBadge';
import NewDepartmentModal from '../components/NewDepartmentModal';
import { displayStatus, humanizeError } from '../lib/status';
import { formatDocDate, formatMoney, timeAgo, formatDateTime } from '../lib/format';
import { API_BASE_URL, getDepartments, bulkUpdateDocumentDepartment, reprocessDocument, bulkReprocessDocuments, errorMessage } from '../api';
import { useToast } from '../components/toastContext';
import './documents.css';

const FILTERS = [
  { key: 'all', label: 'All Statuses', tone: 'muted' },
  { key: 'ready', label: 'Ready', tone: 'ok' },
  { key: 'review', label: 'Needs review', tone: 'warn' },
  { key: 'processing', label: 'Processing', tone: 'info' },
  { key: 'error', label: 'Failed', tone: 'bad' },
];

const SORTS = {
  newest: { label: 'Newest first', fn: (a, b) => b.created_at.localeCompare(a.created_at) },
  oldest: { label: 'Oldest first', fn: (a, b) => a.created_at.localeCompare(b.created_at) },
  confidence: { label: 'Lowest confidence', fn: (a, b) => (a.summary?.avg_confidence ?? 2) - (b.summary?.avg_confidence ?? 2) },
  name: { label: 'Name A–Z', fn: (a, b) => a.filename.localeCompare(b.filename) },
};

function RowMenu({ doc, onOpen, onDelete, onRetry }) {
  const exportUrl = (format) => `${API_BASE_URL}/documents/${doc.doc_id}/export?format=${format}`;
  const ready = doc.status === 'completed';
  return (
    <DropdownMenu
      label={`Actions for ${doc.filename}`}
      trigger={({ toggle, open, label }) => (
        <button className={`btn btn-ghost btn-sm btn-icon row-menu ${open ? 'open' : ''}`} onClick={toggle} aria-label={label} aria-expanded={open}>
          <MoreHorizontal size={16} />
        </button>
      )}
    >
      {(close) => (
        <>
          <button className="menu-item" onClick={() => { close(); onOpen(); }}><ArrowUpRight size={16} /> Open</button>
          {onRetry && (
            <button className="menu-item" onClick={() => { close(); onRetry(); }}><RefreshCw size={16} /> Retry processing</button>
          )}
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

export default function Documents({ documents, loaded, navigate, onUpload, onFiles, onDelete, onRefresh, query }) {
  const status = FILTERS.some((f) => f.key === query.status) ? query.status : 'all';
  const notify = useToast();
  const [search, setSearch] = useState('');
  const [fromDate, setFromDate] = useState('');
  const [sort, setSort] = useState('newest');
  const [selected, setSelected] = useState(new Set());
  const [viewMode, setViewMode] = useState(() => (query?.view === 'batches' ? 'batches' : 'flat'));
  const [collapsedBatches, setCollapsedBatches] = useState(new Set());
  const [departments, setDepartments] = useState([]);
  const [retryingIds, setRetryingIds] = useState(new Set());
  const [bulkRetrying, setBulkRetrying] = useState(false);
  const [selectedDept, setSelectedDept] = useState('all');
  const [isNewDeptModalOpen, setIsNewDeptModalOpen] = useState(false);
  const [bulkMoving, setBulkMoving] = useState(false);
  const [showBulkMoveMenu, setShowBulkMoveMenu] = useState(false);
  const searchRef = useRef(null);

  useEffect(() => {
    if (query?.view === 'batches') {
      setViewMode('batches');
    } else if (query?.view === 'flat') {
      setViewMode('flat');
    }
  }, [query?.view]);

  const fetchDepartments = async () => {
    try {
      const res = await getDepartments();
      setDepartments(res.data || []);
    } catch (err) {
      console.error('Failed to load departments:', err);
    }
  };

  useEffect(() => {
    fetchDepartments();
  }, []);

  // "/" shortcut focuses search
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
    documents.forEach((d) => {
      const s = displayStatus(d);
      if (c[s] !== undefined) c[s] += 1;
    });
    return c;
  }, [documents]);

  const deptCounts = useMemo(() => {
    const c = { all: documents.length };
    documents.forEach((d) => {
      const dept = d.department || 'General';
      c[dept] = (c[dept] || 0) + 1;
    });
    return c;
  }, [documents]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return documents
      .filter((d) => status === 'all' || displayStatus(d) === status)
      .filter((d) => selectedDept === 'all' || (d.department || 'General').toLowerCase() === selectedDept.toLowerCase())
      .filter((d) => !fromDate || d.created_at.slice(0, 10) >= fromDate)
      .filter((d) => {
        if (!q) return true;
        const s = d.summary || {};
        return [d.filename, s.customer, s.title, s.amount_raw, d.department].some((v) => v && String(v).toLowerCase().includes(q));
      })
      .sort(SORTS[sort].fn);
  }, [documents, status, selectedDept, fromDate, search, sort]);

  const groupedBatches = useMemo(() => {
    const batchMap = new Map();
    const singles = [];

    rows.forEach((doc) => {
      if (doc.batch_id) {
        if (!batchMap.has(doc.batch_id)) {
          batchMap.set(doc.batch_id, []);
        }
        batchMap.get(doc.batch_id).push(doc);
      } else {
        singles.push(doc);
      }
    });

    const list = [];
    batchMap.forEach((batchDocs, batchId) => {
      const latestTime = batchDocs.reduce((latest, d) => (d.created_at > latest ? d.created_at : latest), batchDocs[0]?.created_at || '');
      const completedCount = batchDocs.filter((d) => d.status === 'completed' && displayStatus(d) !== 'review').length;
      const reviewCount = batchDocs.filter((d) => displayStatus(d) === 'review').length;
      const processingCount = batchDocs.filter((d) => d.status === 'processing' || d.status === 'queued').length;
      const errorCount = batchDocs.filter((d) => d.status === 'error').length;
      const totalPages = batchDocs.reduce((sum, d) => sum + (d.summary?.pages || 0), 0);

      const leadDoc = batchDocs[0];
      const leadName = leadDoc?.filename || 'Contract';
      const remainingCount = batchDocs.length - 1;

      const uniqueDepts = Array.from(new Set(batchDocs.map((d) => d.department || 'General')));
      const dominantDept = uniqueDepts.length === 1 ? uniqueDepts[0] : null;

      list.push({
        batchId,
        created_at: latestTime,
        docs: batchDocs,
        leadName,
        remainingCount,
        dominantDept,
        totalPages,
        completedCount,
        reviewCount,
        processingCount,
        errorCount,
      });
    });

    list.sort((a, b) => b.created_at.localeCompare(a.created_at));

    return { batches: list, singles };
  }, [rows]);

  const toggleBatch = (batchId) => {
    setCollapsedBatches((prev) => {
      const next = new Set(prev);
      if (next.has(batchId)) next.delete(batchId);
      else next.add(batchId);
      return next;
    });
  };

  const setStatus = (key) => {
    navigate(key === 'all' ? '/documents' : `/documents?status=${key}`);
    setSelected(new Set());
  };

  const hasFilters = Boolean(search || fromDate || selectedDept !== 'all' || status !== 'all' || sort !== 'newest');
  const clearFilters = () => {
    setSearch('');
    setFromDate('');
    setSelectedDept('all');
    setSort('newest');
    setStatus('all');
    setSelected(new Set());
  };

  const isSomeSelected = selected.size > 0;

  const toggleOne = (e, id) => {
    e.stopPropagation();
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  const bulkDelete = () => {
    if (!window.confirm(`Delete ${selected.size} selected documents?`)) return;
    const docsToDelete = documents.filter((d) => selected.has(d.doc_id));
    docsToDelete.forEach((d) => onDelete(d));
    setSelected(new Set());
  };

  const bulkExportJson = () => {
    const data = documents.filter((d) => selected.has(d.doc_id));
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `smartextractor_export_${selected.size}.json`;
    a.click();
    URL.revokeObjectURL(url);
    setSelected(new Set());
  };

  const handleRetryOne = async (docId) => {
    setRetryingIds((prev) => new Set([...prev, docId]));
    try {
      await reprocessDocument(docId);
      notify('Queued for reprocessing', 'info');
      if (onRefresh) onRefresh();
    } catch (err) {
      notify(errorMessage(err, 'Failed to retry document'), 'error');
    } finally {
      setRetryingIds((prev) => {
        const next = new Set(prev);
        next.delete(docId);
        return next;
      });
    }
  };

  const handleRetrySelected = async () => {
    if (!selected.size) return;
    setBulkRetrying(true);
    try {
      const ids = Array.from(selected);
      await bulkReprocessDocuments(ids);
      notify(`${ids.length} document${ids.length > 1 ? 's' : ''} queued for reprocessing`, 'info');
      setSelected(new Set());
      if (onRefresh) onRefresh();
    } catch (err) {
      notify(errorMessage(err, 'Failed to retry selected documents'), 'error');
    } finally {
      setBulkRetrying(false);
    }
  };

  const handleRetryAllFailed = async () => {
    const failedDocs = rows.filter((d) => d.status === 'error' || displayStatus(d) === 'error');
    if (!failedDocs.length) return;
    setBulkRetrying(true);
    try {
      const ids = failedDocs.map((d) => d.doc_id);
      await bulkReprocessDocuments(ids);
      notify(`Retrying ${ids.length} failed document${ids.length > 1 ? 's' : ''}`, 'info');
      if (onRefresh) onRefresh();
    } catch (err) {
      notify(errorMessage(err, 'Failed to retry failed documents'), 'error');
    } finally {
      setBulkRetrying(false);
    }
  };

  const handleRetryBatch = async (batch) => {
    const failedDocs = batch.docs.filter((d) => d.status === 'error' || displayStatus(d) === 'error');
    if (!failedDocs.length) return;
    setBulkRetrying(true);
    try {
      const ids = failedDocs.map((d) => d.doc_id);
      await bulkReprocessDocuments(ids);
      notify(`Retrying ${ids.length} failed document${ids.length > 1 ? 's' : ''} in batch`, 'info');
      if (onRefresh) onRefresh();
    } catch (err) {
      notify(errorMessage(err, 'Failed to retry batch documents'), 'error');
    } finally {
      setBulkRetrying(false);
    }
  };

  const exportBatchJson = (batch) => {
    const blob = new Blob([JSON.stringify(batch.docs, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `smartextractor_batch_${(batch.batchId || 'bulk').slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const title = { all: 'Documents', ready: 'Ready to use', review: 'Needs review', processing: 'Processing', error: 'Failed' }[status];
  const subtitle = {
    all: 'Everything you have uploaded, newest first.',
    ready: 'Extracted and checked — safe to export.',
    review: 'These have missing fields or low confidence. Open one to confirm or correct.',
    processing: 'Being read right now. This page updates automatically.',
    error: 'These files encountered processing issues. You can retry them directly without re-uploading.',
  }[status];

  const handleDocDeptChanged = (docId, newDept) => {
    const target = documents.find((d) => d.doc_id === docId);
    if (target) {
      target.department = newDept;
    }
    fetchDepartments();
    setSelectedDept((curr) => curr);
  };

  const handleBulkMove = async (targetDept) => {
    setShowBulkMoveMenu(false);
    if (!selected.size) return;
    setBulkMoving(true);
    try {
      await bulkUpdateDocumentDepartment(Array.from(selected), targetDept);
      documents.forEach((d) => {
        if (selected.has(d.doc_id)) {
          d.department = targetDept;
        }
      });
      fetchDepartments();
      setSelected(new Set());
    } catch (err) {
      console.error('Failed to bulk move documents:', err);
    } finally {
      setBulkMoving(false);
    }
  };

  const renderTableHeader = (docsSubset) => {
    const isSubsetAllSelected = docsSubset.length > 0 && docsSubset.every((d) => selected.has(d.doc_id));
    const toggleSubset = () => {
      setSelected((prev) => {
        const next = new Set(prev);
        if (isSubsetAllSelected) {
          docsSubset.forEach((d) => next.delete(d.doc_id));
        } else {
          docsSubset.forEach((d) => next.add(d.doc_id));
        }
        return next;
      });
    };

    return (
      <thead>
        <tr>
          <th className="checkbox-cell">
            <button
              type="button"
              className="bulk-check"
              onClick={toggleSubset}
              aria-label="Select all"
            >
              {isSubsetAllSelected ? <CheckSquare size={15} /> : <Square size={15} />}
            </button>
          </th>
          <th>Document</th>
          <th>Category</th>
          <th>Status</th>
          <th>Uploaded</th>
          <th><span className="sr-only">Actions</span></th>
        </tr>
      </thead>
    );
  };

  const renderRow = (doc) => {
    const s = doc.summary || {};
    const open = () => navigate(`/documents/${doc.doc_id}`);
    const isSelected = selected.has(doc.doc_id);
    const fieldsTotal = s.fields_total || 6;
    const fieldsFound = s.fields_found || 0;
    const isComplete = doc.status === 'completed' && fieldsFound === fieldsTotal;

    return (
      <tr
        key={doc.doc_id}
        onClick={open}
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && open()}
        className={`doc-row ${isSelected ? 'selected-row' : ''}`}
      >
        <td className="checkbox-cell" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="bulk-check"
            onClick={(e) => toggleOne(e, doc.doc_id)}
            aria-label={isSelected ? 'Deselect row' : 'Select row'}
          >
            {isSelected ? <CheckSquare size={15} /> : <Square size={15} />}
          </button>
        </td>

        <td className="doc-main-cell">
          <div className="doc-cell">
            <FileIcon filename={doc.filename} size={28} />
            <div className="doc-meta-block">
              <span className="doc-name" title={doc.filename}>{doc.filename}</span>
              <div className="doc-sub">
                {doc.status === 'error' ? (
                  (() => {
                    const err = humanizeError(doc.error);
                    return (
                      <span className="bad-text" title={err.technical || err.description}>
                        <CircleAlert size={12} style={{ display: 'inline', marginRight: '4px', verticalAlign: '-1px' }} />
                        <b>{err.title}:</b> {err.description}
                      </span>
                    );
                  })()
                ) : (
                  <>
                    {s.title && s.title !== doc.filename ? <span className="doc-title-snippet">{s.title}</span> : null}
                    {s.pages ? <span className="doc-pages">{s.pages} page{s.pages > 1 ? 's' : ''}</span> : null}
                  </>
                )}
              </div>
            </div>
          </div>
        </td>

        <td className="directory-cell" onClick={(e) => e.stopPropagation()}>
          <DepartmentBadge
            department={doc.department || 'General'}
            docId={doc.doc_id}
            departments={departments}
            onDepartmentChanged={(newDept) => handleDocDeptChanged(doc.doc_id, newDept)}
            onOpenCreateModal={() => setIsNewDeptModalOpen(true)}
            size="sm"
          />
        </td>

        <td className="status-cell">
          <StatusBadge doc={doc} />
        </td>

        <td className="uploaded-cell nowrap muted" title={formatDateTime(doc.created_at)}>
          {timeAgo(doc.created_at)}
        </td>

        <td className="actions-cell" onClick={(e) => e.stopPropagation()}>
          <div className="row-actions-group">
            {(doc.status === 'error' || displayStatus(doc) === 'error') && (
              <button
                type="button"
                className="btn-row-retry"
                onClick={() => handleRetryOne(doc.doc_id)}
                disabled={retryingIds.has(doc.doc_id)}
                title="Retry processing this file"
              >
                <RefreshCw size={12} className={retryingIds.has(doc.doc_id) ? 'spin' : ''} />
                <span>{retryingIds.has(doc.doc_id) ? 'Retrying...' : 'Retry'}</span>
              </button>
            )}
            <RowMenu
              doc={doc}
              onOpen={open}
              onDelete={onDelete}
              onRetry={(doc.status === 'error' || displayStatus(doc) === 'error') ? () => handleRetryOne(doc.doc_id) : null}
            />
          </div>
        </td>
      </tr>
    );
  };

  const renderTable = (docsSubset) => (
    <div className="table-scroll">
      <table className="doc-table">
        {renderTableHeader(docsSubset)}
        <tbody>
          {docsSubset.map(renderRow)}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="page documents-page">
      {/* Page Header (Clean, spacious, Upload in sidebar) */}
      <PageHeader
        eyebrow="Library"
        title={title}
        subtitle={subtitle}
      />

      {/* Single-Line Toolbar with Rich Dropdown Controls */}
      <div className="clean-toolbar">
        <div className="toolbar-filters-row">
          {/* Search */}
          <label className="clean-search-field">
            <Search size={14} className="clean-search-icon" />
            <input
              ref={searchRef}
              className="clean-search-input"
              placeholder="Search file name, title…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {!search && <kbd className="clean-kbd">/</kbd>}
          </label>

          <div className="filter-divider" />

          {/* Directory Filter (Rich Custom Dropdown) */}
          <DropdownMenu
            align="left"
            trigger={({ toggle, open }) => {
              const activeDeptTheme = selectedDept !== 'all' ? getDepartmentTheme(selectedDept) : null;
              const ActiveIcon = activeDeptTheme ? activeDeptTheme.icon : Folder;
              return (
                <button
                  type="button"
                  className={`filter-pill-trigger ${open ? 'open' : ''} ${selectedDept !== 'all' ? 'has-value' : ''}`}
                  onClick={toggle}
                  aria-label="Filter by category"
                >
                  <ActiveIcon size={14} style={{ color: activeDeptTheme ? activeDeptTheme.color : 'var(--ink-3)' }} />
                  <span className="filter-pill-label">
                    {selectedDept === 'all' ? 'All Categories' : selectedDept}
                  </span>
                  <span className="filter-pill-count">{deptCounts[selectedDept] || 0}</span>
                  <ChevronDown size={12} className="filter-pill-arrow" />
                </button>
              );
            }}
          >
            {(close) => (
              <div className="filter-popover-menu">
                <div className="filter-popover-header">Filter by Category</div>
                <button
                  type="button"
                  className={`filter-popover-item ${selectedDept === 'all' ? 'active' : ''}`}
                  onClick={() => { setSelectedDept('all'); close(); }}
                >
                  <Folder size={14} style={{ color: 'var(--ink-3)' }} />
                  <span className="popover-item-text">All Categories</span>
                  <span className="popover-item-count">{deptCounts['all'] || 0}</span>
                  {selectedDept === 'all' && <Check size={14} className="popover-item-check" />}
                </button>
                <div className="menu-sep" />
                {(departments.length > 0 ? departments : [
                  { name: 'Data Center', id: 'dept_data_center' },
                  { name: 'Cloud Services', id: 'dept_cloud_services' },
                  { name: 'General', id: 'dept_general' },
                ]).map((dept) => {
                  const theme = getDepartmentTheme(dept.name);
                  const Icon = theme.icon;
                  const count = deptCounts[dept.name] || 0;
                  const isSelected = selectedDept.toLowerCase() === dept.name.toLowerCase();
                  return (
                    <button
                      key={dept.id || dept.name}
                      type="button"
                      className={`filter-popover-item ${isSelected ? 'active' : ''}`}
                      onClick={() => { setSelectedDept(dept.name); close(); }}
                    >
                      <Icon size={14} style={{ color: theme.color }} />
                      <span className="popover-item-text">{dept.name}</span>
                      <span className="popover-item-count">{count}</span>
                      {isSelected && <Check size={14} className="popover-item-check" />}
                    </button>
                  );
                })}
                <div className="menu-sep" />
                <button
                  type="button"
                  className="filter-popover-item action-item"
                  onClick={() => { close(); setIsNewDeptModalOpen(true); }}
                >
                  <FolderPlus size={14} />
                  <span className="popover-item-text">New Category...</span>
                </button>
              </div>
            )}
          </DropdownMenu>

          {/* Status Filter (Rich Custom Dropdown with glowing dots) */}
          <DropdownMenu
            align="left"
            trigger={({ toggle, open }) => {
              const activeMeta = FILTERS.find((f) => f.key === status) || FILTERS[0];
              return (
                <button
                  type="button"
                  className={`filter-pill-trigger ${open ? 'open' : ''} ${status !== 'all' ? 'has-value' : ''}`}
                  onClick={toggle}
                  aria-label="Filter by status"
                >
                  <span className={`status-glow-dot tone-${activeMeta.tone}`} />
                  <span className="filter-pill-label">{activeMeta.label}</span>
                  <span className="filter-pill-count">{counts[status] || 0}</span>
                  <ChevronDown size={12} className="filter-pill-arrow" />
                </button>
              );
            }}
          >
            {(close) => (
              <div className="filter-popover-menu">
                <div className="filter-popover-header">Filter by Status</div>
                {FILTERS.map((f) => {
                  const isSelected = status === f.key;
                  const count = counts[f.key] || 0;
                  return (
                    <button
                      key={f.key}
                      type="button"
                      className={`filter-popover-item ${isSelected ? 'active' : ''}`}
                      onClick={() => { setStatus(f.key); close(); }}
                    >
                      <span className={`status-glow-dot tone-${f.tone}`} />
                      <span className="popover-item-text">{f.label}</span>
                      <span className="popover-item-count">{count}</span>
                      {isSelected && <Check size={14} className="popover-item-check" />}
                    </button>
                  );
                })}
              </div>
            )}
          </DropdownMenu>

          {/* Date Range Picker */}
          <div className={`filter-date-pill ${fromDate ? 'has-value' : ''}`} title="Filter by upload date">
            <input
              type="date"
              className="filter-date-input"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              aria-label="Filter by date"
            />
          </div>

          {/* Sort Dropdown */}
          <DropdownMenu
            align="left"
            trigger={({ toggle, open }) => (
              <button
                type="button"
                className={`filter-pill-trigger ${open ? 'open' : ''} ${sort !== 'newest' ? 'has-value' : ''}`}
                onClick={toggle}
                aria-label="Sort documents"
              >
                <span className="filter-pill-dim">Sort:</span>
                <span className="filter-pill-label">{SORTS[sort]?.label}</span>
                <ChevronDown size={12} className="filter-pill-arrow" />
              </button>
            )}
          >
            {(close) => (
              <div className="filter-popover-menu">
                <div className="filter-popover-header">Sort Documents</div>
                {Object.entries(SORTS).map(([key, s]) => {
                  const isSelected = sort === key;
                  return (
                    <button
                      key={key}
                      type="button"
                      className={`filter-popover-item ${isSelected ? 'active' : ''}`}
                      onClick={() => { setSort(key); close(); }}
                    >
                      <span className="popover-item-text">{s.label}</span>
                      {isSelected && <Check size={14} className="popover-item-check" />}
                    </button>
                  );
                })}
              </div>
            )}
          </DropdownMenu>

          {hasFilters && (
            <button type="button" className="clean-clear-btn" onClick={clearFilters} title="Reset all filters">
              <X size={13} />
              <span>Clear</span>
            </button>
          )}
        </div>

        <div className="toolbar-controls-row">
          {/* Retry All Failed Button */}
          {status === 'error' && rows.length > 0 && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleRetryAllFailed}
              disabled={bulkRetrying}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
            >
              <RefreshCw size={13} className={bulkRetrying ? 'spin' : ''} />
              <span>{bulkRetrying ? 'Retrying...' : `Retry All Failed (${rows.length})`}</span>
            </button>
          )}

          {/* Minimal View Mode Toggle */}
          <div className="clean-view-toggle" role="group" aria-label="View layout">
            <button
              type="button"
              className={`view-toggle-btn ${viewMode === 'flat' ? 'active' : ''}`}
              onClick={() => {
                setViewMode('flat');
                navigate(status !== 'all' ? `/documents?status=${status}` : '/documents');
              }}
              title="Flat list (All files)"
            >
              <FileText size={13} />
              <span>List</span>
            </button>
            <button
              type="button"
              className={`view-toggle-btn ${viewMode === 'batches' ? 'active' : ''}`}
              onClick={() => {
                setViewMode('batches');
                navigate(status !== 'all' ? `/documents?status=${status}&view=batches` : '/documents?view=batches');
              }}
              title="Group by batch"
            >
              <Layers size={13} />
              <span>Batches</span>
            </button>
          </div>
        </div>
      </div>

      {/* Floating/Docked Bulk Action Bar */}
      {isSomeSelected && (
        <div className="bulk-toolbar-clean">
          <span className="bulk-count">{selected.size} document{selected.size > 1 ? 's' : ''} selected</span>
          <div className="bulk-actions-group">
            <button className="btn btn-ghost btn-sm" onClick={() => setSelected(new Set())}>Cancel</button>

            <div style={{ position: 'relative', display: 'inline-block' }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setShowBulkMoveMenu((v) => !v)}
                disabled={bulkMoving}
              >
                <Folder size={13} /> Move to Category <ChevronDown size={11} />
              </button>
              {showBulkMoveMenu && (
                <div className="dept-menu-popover" style={{ right: 0, left: 'auto', width: '220px', zIndex: 1200 }}>
                  <div className="dept-menu-header">Select Target Category</div>
                  <div className="dept-menu-list">
                    {(departments.length > 0 ? departments.map((d) => d.name) : ['Data Center', 'Cloud Services', 'General']).map((dName) => {
                      const dTheme = getDepartmentTheme(dName);
                      const DIcon = dTheme.icon;
                      return (
                        <button
                          key={dName}
                          type="button"
                          className="dept-menu-item"
                          onClick={() => handleBulkMove(dName)}
                        >
                          <DIcon size={14} style={{ color: dTheme.color }} />
                          <span className="dept-item-label">{dName}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleRetrySelected}
              disabled={bulkRetrying}
              style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}
            >
              <RefreshCw size={12} className={bulkRetrying ? 'spin' : ''} />
              <span>Retry Selected</span>
            </button>
            <button className="btn btn-secondary btn-sm" onClick={bulkExportJson}><FileJson size={14} /> Export JSON</button>
            <button className="btn btn-danger btn-sm" onClick={bulkDelete}><Trash2 size={14} /> Delete</button>
          </div>
        </div>
      )}

      {/* Flat Table Area */}
      {!loaded ? (
        <div className="flat-table-wrap">
          <div className="table-skeleton">
            {Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton" style={{ height: 42 }} />)}
          </div>
        </div>
      ) : !documents.length ? (
        <div className="flat-table-wrap">
          <div className="table-empty">
            <UploadDropzone onBrowse={onUpload} onFiles={onFiles} />
          </div>
        </div>
      ) : !rows.length ? (
        <div className="flat-table-wrap">
          <EmptyState
            icon={<SearchX size={26} />}
            title="Nothing matches"
            action={hasFilters && <button className="btn btn-secondary" onClick={clearFilters}>Clear filters</button>}
          >
            {status === 'review' && !search ? 'No documents need review. Everything has been checked.' : 'Try a different search or filter.'}
          </EmptyState>
        </div>
      ) : viewMode === 'batches' && status !== 'error' ? (
        groupedBatches.batches.length > 0 ? (
          <div className="batch-groups-wrap">
            {groupedBatches.batches.map((b) => {
              const isCollapsed = collapsedBatches.has(b.batchId);
              return (
                <div key={b.batchId} className="batch-minimal-group">
                  <div
                    className="batch-minimal-header"
                    onClick={() => toggleBatch(b.batchId)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => e.key === 'Enter' && toggleBatch(b.batchId)}
                  >
                    <div className="batch-header-left">
                      <button
                        type="button"
                        className="btn-icon batch-chevron"
                        aria-label={isCollapsed ? 'Expand batch' : 'Collapse batch'}
                      >
                        {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                      </button>
                      <div className="batch-title-block">
                        <div className="batch-title-row">
                          <Layers size={14} className="batch-icon" />
                          <span className="batch-lead-name" title={b.leadName}>“{b.leadName}”</span>
                          {b.remainingCount > 0 && (
                            <span className="batch-remaining-tag">+{b.remainingCount} more</span>
                          )}
                          {b.dominantDept && (
                            <span className="batch-dept-tag">{b.dominantDept}</span>
                          )}
                        </div>
                        <div className="batch-meta-row muted">
                          <span>{timeAgo(b.created_at)}</span>
                          <span className="dot-sep">{b.docs.length} files</span>
                          {b.totalPages > 0 && <span className="dot-sep">{b.totalPages} pages</span>}
                        </div>
                      </div>

                      <div className="batch-header-badges">
                        {b.completedCount > 0 && (
                          <span className="badge badge-ok"><Check size={11} /> {b.completedCount} Ready</span>
                        )}
                        {b.reviewCount > 0 && (
                          <span className="badge badge-warn">{b.reviewCount} Review</span>
                        )}
                        {b.processingCount > 0 && (
                          <span className="badge badge-info"><RefreshCw size={11} className="spin" /> {b.processingCount} Processing</span>
                        )}
                        {b.errorCount > 0 && (
                          <span className="badge badge-bad"><CircleAlert size={11} /> {b.errorCount} Failed</span>
                        )}
                      </div>
                    </div>

                    <div className="batch-header-actions" onClick={(e) => e.stopPropagation()}>
                      {b.errorCount > 0 && (
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          style={{ padding: '2px 9px', fontSize: '12px', height: '26px', gap: '4px' }}
                          onClick={() => handleRetryBatch(b)}
                          disabled={bulkRetrying}
                          title="Retry all failed files in this batch"
                        >
                          <RefreshCw size={12} className={bulkRetrying ? 'spin' : ''} />
                          <span>Retry Failed ({b.errorCount})</span>
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm btn-icon"
                        style={{ width: '28px', height: '28px' }}
                        onClick={() => exportBatchJson(b)}
                        title="Export batch data as JSON"
                      >
                        <Download size={14} />
                      </button>
                    </div>
                  </div>
                  {!isCollapsed && renderTable(b.docs)}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="flat-table-wrap">
            <EmptyState
              icon={<Layers size={28} />}
              title="No bulk batches found"
              action={<button className="btn btn-secondary btn-sm" onClick={() => setViewMode('flat')}>Switch to List view</button>}
            >
              All current documents were uploaded individually. Switch to List view to see them.
            </EmptyState>
          </div>
        )
      ) : (
        <div className="flat-table-wrap">
          {renderTable(rows)}
        </div>
      )}

      {loaded && rows.length > 0 && (
        <p className="table-foot muted">
          Showing {rows.length} of {documents.length} · Press <kbd className="clean-kbd">/</kbd> to search
        </p>
      )}

      <NewDepartmentModal
        isOpen={isNewDeptModalOpen}
        onClose={() => setIsNewDeptModalOpen(false)}
        onCreated={(newDept) => {
          fetchDepartments();
          setSelectedDept(newDept.name);
        }}
      />
    </div>
  );
}
