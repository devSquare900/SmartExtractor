import { useEffect, useRef, useState } from 'react';
import { ZoomIn, ZoomOut, ChevronLeft, ChevronRight, Download, ExternalLink, ScanText, Maximize } from 'lucide-react';
import { api, API_BASE_URL, serverUrl } from '../api';
import { useToast } from './toastContext';

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const ZOOM_STEP = 0.25;

const boxStyle = (box, width, height) => {
  const xs = box.map((pt) => pt[0]);
  const ys = box.map((pt) => pt[1]);
  const x0 = Math.min(...xs);
  const y0 = Math.min(...ys);
  return {
    left: `${(x0 / width) * 100}%`,
    top: `${(y0 / height) * 100}%`,
    width: `${((Math.max(...xs) - x0) / width) * 100}%`,
    height: `${((Math.max(...ys) - y0) / height) * 100}%`,
  };
};

export default function Viewer({ doc, activeBox, threshold = 0.85 }) {
  const notify = useToast();
  const [images, setImages] = useState(null);
  const [page, setPage] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [natural, setNatural] = useState({ w: 1, h: 1 });
  const [showText, setShowText] = useState(false);
  const [ocrPages, setOcrPages] = useState(null);
  const [lastBox, setLastBox] = useState(activeBox);
  const canvasRef = useRef(null);
  const highlightRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    api.get(`/documents/${doc.doc_id}/images`)
      .then((r) => !cancelled && setImages(r.data))
      .catch(() => !cancelled && setImages([]));
    return () => { cancelled = true; };
  }, [doc.doc_id]);

  // Follow the focused field to its page.
  if (activeBox !== lastBox) {
    setLastBox(activeBox);
    if (activeBox?.page_num && images && activeBox.page_num <= images.length) setPage(activeBox.page_num - 1);
  }

  // Scroll the highlight into view once it is rendered.
  useEffect(() => {
    highlightRef.current?.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
  }, [activeBox, page, natural]);

  // Ctrl/Cmd + scroll zooms (needs a non-passive listener to stop page zoom).
  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return undefined;
    const onWheel = (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, +(z + (e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP)).toFixed(2))));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [images]);

  const toggleText = async () => {
    if (!showText && !ocrPages) {
      try {
        const r = await api.get(`/documents/${doc.doc_id}/ocr`);
        setOcrPages(r.data.pages || []);
      } catch {
        notify('Could not load text boxes', 'error');
        return;
      }
    }
    setShowText((v) => !v);
  };

  const changeZoom = (delta) => setZoom((z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, +(z + delta).toFixed(2))));

  if (images === null) {
    return <div className="viewer"><div className="viewer-canvas"><div className="viewer-loading skeleton" /></div></div>;
  }
  if (!images.length) {
    return <div className="viewer"><div className="viewer-canvas viewer-empty">No page preview available</div></div>;
  }

  const blocks = showText ? ocrPages?.[page]?.blocks || [] : [];
  const showHighlight = activeBox?.box && activeBox.page_num === page + 1;

  return (
    <div className="viewer">
      <div className="viewer-toolbar" role="toolbar" aria-label="Page viewer">
        <div className="tb-group">
          <button className="tb-btn" onClick={() => changeZoom(-ZOOM_STEP)} disabled={zoom <= MIN_ZOOM} aria-label="Zoom out"><ZoomOut size={16} /></button>
          <button className="tb-zoom mono" onClick={() => setZoom(1)} title="Reset to fit width">{Math.round(zoom * 100)}%</button>
          <button className="tb-btn" onClick={() => changeZoom(ZOOM_STEP)} disabled={zoom >= MAX_ZOOM} aria-label="Zoom in"><ZoomIn size={16} /></button>
          <button className="tb-btn" onClick={() => setZoom(1)} aria-label="Fit width"><Maximize size={15} /></button>
        </div>
        <div className="tb-group">
          <button className="tb-btn" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} aria-label="Previous page"><ChevronLeft size={17} /></button>
          <span className="tb-page mono">{page + 1} / {images.length}</span>
          <button className="tb-btn" onClick={() => setPage((p) => Math.min(images.length - 1, p + 1))} disabled={page === images.length - 1} aria-label="Next page"><ChevronRight size={17} /></button>
        </div>
        <div className="tb-group">
          <button className={`tb-toggle ${showText ? 'on' : ''}`} onClick={toggleText} aria-pressed={showText}
            title="Outline every piece of text found (red = low confidence)">
            <ScanText size={15} /> Text layer
          </button>
          <a className="tb-btn" href={`${API_BASE_URL}/documents/${doc.doc_id}/file`} download aria-label="Download original"><Download size={16} /></a>
          <a className="tb-btn" href={serverUrl(images[page])} target="_blank" rel="noreferrer" aria-label="Open page in new tab"><ExternalLink size={15} /></a>
        </div>
      </div>

      <div className="viewer-body">
        {images.length > 1 && (
          <nav className="thumbs" aria-label="Pages">
            {images.map((src, i) => (
              <button
                key={src}
                className={`thumb ${i === page ? 'active' : ''} ${activeBox?.page_num === i + 1 ? 'has-hl' : ''}`}
                onClick={() => setPage(i)}
                aria-label={`Page ${i + 1}`}
                aria-current={i === page ? 'page' : undefined}
              >
                <img src={serverUrl(src)} alt="" loading="lazy" />
                <span className="mono">{i + 1}</span>
              </button>
            ))}
          </nav>
        )}

        <div className="viewer-canvas" ref={canvasRef}>
          <div className="page-sheet" style={{ width: `${zoom * 100}%` }}>
            <img
              src={serverUrl(images[page])}
              alt={`Page ${page + 1} of ${doc.filename}`}
              onLoad={(e) => setNatural({ w: e.target.naturalWidth, h: e.target.naturalHeight })}
            />
            {blocks.map((b, i) => (
              <span
                key={i}
                className={`text-box ${b.confidence < threshold ? 'low' : ''}`}
                style={boxStyle(b.box, natural.w, natural.h)}
                title={`${b.text} · ${Math.round(b.confidence * 100)}%`}
              />
            ))}
            {showHighlight && (
              <span ref={highlightRef} className="hl-box" style={boxStyle(activeBox.box, natural.w, natural.h)}>
                {activeBox.label && <span className="hl-tag">{activeBox.label}</span>}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
