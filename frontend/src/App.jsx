import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, errorMessage } from './api';
import { useHashRoute } from './lib/useHashRoute';
import { computeStats, displayStatus } from './lib/status';
import { useToast } from './components/toastContext';
import NavRail from './components/NavRail';
import UploadTray from './components/UploadTray';
import DropOverlay from './components/DropOverlay';
import ConfirmDialog from './components/ConfirmDialog';
import Overview from './pages/Overview';
import Documents from './pages/Documents';
import Review from './pages/Review';
import PortfolioAssistant from './pages/PortfolioAssistant';
import OfflineOverlay from './components/OfflineOverlay';
import { ACCEPTED_TYPES } from './lib/uploads';

const POLL_INTERVAL_MS = 3000;

function initialTheme() {
  const set = document.documentElement.dataset.theme;
  if (set) return set;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function initialNavCollapsed() {
  try {
    const saved = localStorage.getItem('se-nav');
    if (saved) return saved === 'collapsed';
  } catch {
    /* storage unavailable */
  }
  return window.innerWidth < 1180;
}

export default function App() {
  const notify = useToast();
  const dirtyRef = useRef(false);
  const [route, navigate, pendingNavigation, resolveNavigation] = useHashRoute(dirtyRef);

  const [documents, setDocuments] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [online, setOnline] = useState(true);
  const [uploads, setUploads] = useState([]);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [theme, setTheme] = useState(initialTheme);
  const [navCollapsed, setNavCollapsed] = useState(initialNavCollapsed);
  const fileInputRef = useRef(null);
  const uploadingRef = useRef(false);

  // (Offline notification removed in favor of OfflineOverlay)

  const stats = useMemo(() => computeStats(documents), [documents]);

  // ----- Theme -----
  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem('se-theme', next);
    } catch {
      /* storage unavailable */
    }
  };

  const toggleNav = () => {
    setNavCollapsed((c) => {
      try {
        localStorage.setItem('se-nav', c ? 'expanded' : 'collapsed');
      } catch {
        /* storage unavailable */
      }
      return !c;
    });
  };

  // ----- Documents -----
  const fetchDocuments = useCallback(async () => {
    try {
      const response = await api.get('/documents');
      setDocuments(response.data);
      setOnline(true);
    } catch {
      setOnline(false);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  // Poll while something is processing
  useEffect(() => {
    if (stats.processing === 0 || !online) return undefined;
    const interval = setInterval(fetchDocuments, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [stats.processing, online, fetchDocuments]);

  // Announce documents that finish while the user is elsewhere.
  const previousStatuses = useRef({});
  useEffect(() => {
    documents.forEach((d) => {
      if (previousStatuses.current[d.doc_id] !== 'processing') return;
      if (d.status === 'completed') notify(`${d.filename} is ready to review`, 'success');
      if (d.status === 'error') notify(`${d.filename} could not be processed`, 'error');
    });
    previousStatuses.current = Object.fromEntries(documents.map((d) => [d.doc_id, d.status]));
  }, [documents, notify]);

  // Auto-navigate to newly uploaded documents when they finish processing
  const previousUploadPhases = useRef({});
  const hasAutoOpenedRef = useRef(false);

  useEffect(() => {
    uploads.forEach((u) => {
      let phase = u.state;
      if (u.state === 'uploaded') {
        const doc = documents.find((d) => d.doc_id === u.docId);
        const s = displayStatus(doc);
        phase = s === 'processing' ? 'processing' : s === 'error' ? 'failed' : 'done';
      }
      
      const prevPhase = previousUploadPhases.current[u.key];
      if (prevPhase !== 'done' && phase === 'done') {
        if (!hasAutoOpenedRef.current) {
          hasAutoOpenedRef.current = true;
          navigate(`/documents/${u.docId}`);
        }
      }
    });
    
    previousUploadPhases.current = Object.fromEntries(uploads.map((u) => {
      let phase = u.state;
      if (u.state === 'uploaded') {
        const doc = documents.find((d) => d.doc_id === u.docId);
        const s = displayStatus(doc);
        phase = s === 'processing' ? 'processing' : s === 'error' ? 'failed' : 'done';
      }
      return [u.key, phase];
    }));
  }, [uploads, documents, navigate]);

  // ----- Uploads -----
  const handleFiles = useCallback(async (fileList) => {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    if (uploadingRef.current) {
      notify('Please wait for the current uploads to finish', 'info');
      return;
    }
    uploadingRef.current = true;
    hasAutoOpenedRef.current = false;

    const isBulk = files.length > 1;
    const batchId = isBulk ? `batch-${Date.now()}-${Math.random().toString(36).slice(2, 7)}` : null;

    const batch = files.map((file, i) => ({
      key: `${Date.now()}-${i}-${file.name}`, name: file.name, progress: 0, state: 'queued', batchId,
    }));
    setUploads((current) => {
      // Keep existing items in the tray until the user explicitly clears them
      return [...current, ...batch];
    });
    const patch = (key, changes) => setUploads((list) => list.map((u) => (u.key === key ? { ...u, ...changes } : u)));

    const uploadFile = async (i, file) => {
      const { key } = batch[i];
      patch(key, { state: 'uploading' });
      const form = new FormData();
      form.append('file', file);
      if (batchId) {
        form.append('batch_id', batchId);
        form.append('batch_total', files.length);
      }
      try {
        const response = await api.post('/upload', form, {
          onUploadProgress: (e) => e.total && patch(key, { progress: Math.round((e.loaded / e.total) * 100) }),
        });
        patch(key, { state: 'uploaded', progress: 100, docId: response.data.doc_id, batchId: response.data.batch_id });
        fetchDocuments();
      } catch (error) {
        patch(key, { state: 'failed', error: errorMessage(error, 'Upload failed') });
      }
    };

    const CONCURRENCY = 3;
    let index = 0;
    const workerTasks = Array(CONCURRENCY).fill(0).map(async () => {
      while (index < files.length) {
        const currentIndex = index++;
        await uploadFile(currentIndex, files[currentIndex]);
      }
    });
    await Promise.all(workerTasks);
    
    uploadingRef.current = false;
  }, [fetchDocuments, notify]);

  const openFilePicker = () => fileInputRef.current?.click();

  // ----- Delete -----
  const confirmDelete = async () => {
    const doc = deleteTarget;
    setDeleteTarget(null);
    try {
      await api.delete(`/documents/${doc.doc_id}`);
      setDocuments((list) => list.filter((d) => d.doc_id !== doc.doc_id));
      setUploads((list) => list.filter((u) => u.docId !== doc.doc_id));
      notify(`Deleted ${doc.filename}`, 'success');
      if (route.name === 'review' && route.docId === doc.doc_id) {
        dirtyRef.current = false;
        navigate('/documents');
      }
    } catch (error) {
      notify(errorMessage(error, 'Delete failed'), 'error');
    }
  };

  // ----- Unsaved changes guard -----
  const setDirty = useCallback((dirty) => {
    dirtyRef.current = dirty;
  }, []);

  useEffect(() => {
    const onBeforeUnload = (e) => {
      if (dirtyRef.current) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, []);

  const shared = { 
    documents, stats, loaded, online, navigate, 
    onUpload: openFilePicker, onFiles: handleFiles, onDelete: setDeleteTarget,
    onRefresh: fetchDocuments
  };

  let page;
  if (route.name === 'review') {
    page = (
      <Review
        key={route.docId}
        docId={route.docId}
        doc={documents.find((d) => d.doc_id === route.docId)}
        uploads={uploads}
        documents={documents}
        {...shared}
        onDirtyChange={setDirty}
        onChanged={fetchDocuments}
      />
    );
  } else if (route.name === 'documents') {
    page = <Documents {...shared} query={route.query} />;
  } else if (route.name === 'portfolio-ai') {
    page = <PortfolioAssistant {...shared} />;
  } else {
    page = <Overview {...shared} />;
  }

  return (
    <div className={`app-shell ${navCollapsed ? 'nav-collapsed' : ''}`}>
      <NavRail
        route={route}
        navigate={navigate}
        stats={stats}
        online={online}
        theme={theme}
        onToggleTheme={toggleTheme}
        onUploadClick={openFilePicker}
        collapsed={navCollapsed}
        onToggleCollapse={toggleNav}
      />
      <main className="app-main" id="main">
        {page}
      </main>

      {!online && loaded && <OfflineOverlay onRetry={fetchDocuments} />}

      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        accept={ACCEPTED_TYPES}
        onChange={(e) => {
          handleFiles(e.target.files);
          e.target.value = '';
        }}
      />
      <DropOverlay onFiles={handleFiles} />
      <UploadTray
        uploads={uploads}
        documents={documents}
        onOpen={(id) => navigate(`/documents/${id}`)}
        onClear={() => setUploads([])}
      />
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete this document?"
        body={deleteTarget ? `${deleteTarget.filename}, its page images and any edits will be permanently removed.` : ''}
        confirmLabel="Delete document"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
      <ConfirmDialog
        open={Boolean(pendingNavigation)}
        tone="neutral"
        title="Leave without saving?"
        body="You have unsaved changes on this document. They will be lost if you leave."
        confirmLabel="Discard changes"
        onConfirm={() => {
          dirtyRef.current = false;
          resolveNavigation(true);
        }}
        onCancel={() => resolveNavigation(false)}
      />
    </div>
  );
}
