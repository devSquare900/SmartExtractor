import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  FileText, FileSpreadsheet, FileDown, X, Check, Copy,
  Eye, Code2, RefreshCw, Palette, Download, Maximize2, Minimize2
} from 'lucide-react';
import { THEMES } from './artifactUtils';
import { API_BASE_URL, errorMessage } from '../../api';
import { useToast } from '../../components/toastContext';
import './ArtifactCanvas.css';

export default function ArtifactCanvas({
  artifact,
  onClose,
  scope = 'Contract Report',
  onUpdateTheme
}) {
  const [viewMode, setViewMode] = useState('preview'); // 'preview' | 'code'
  const [currentTheme, setCurrentTheme] = useState(artifact?.theme || 'navy');
  const [exportingFmt, setExportingFmt] = useState(null);
  const [copied, setCopied] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const { notify } = useToast();

  if (!artifact) return null;

  const themeObj = THEMES[currentTheme] || THEMES.navy;

  const handleThemeChange = (newTheme) => {
    setCurrentTheme(newTheme);
    if (onUpdateTheme) onUpdateTheme(newTheme);
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(artifact.content || '');
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const handleExport = async (format) => {
    if (!artifact.content) return;
    setExportingFmt(format);
    try {
      const res = await fetch(`${API_BASE_URL}/chat/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: artifact.content,
          format,
          query: artifact.title || 'Document Report',
          scope: scope,
        }),
      });

      if (!res.ok) {
        throw new Error(`Export failed (${res.status})`);
      }

      const disp = res.headers.get('Content-Disposition') || '';
      const match = disp.match(/filename="?([^";]+)"?/);
      const ext = format === 'excel' ? 'xlsx' : format === 'word' ? 'docx' : 'pdf';
      const cleanTitle = (artifact.title || 'Document_Report').replace(/[^a-zA-Z0-9_-]/g, '_');
      const filename = match ? match[1] : `${cleanTitle}.${ext}`;

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      notify(`Exported ${format.toUpperCase()} successfully!`, 'success');
    } catch (err) {
      console.error(err);
      notify(errorMessage(err, 'Failed to export document'), 'error');
    } finally {
      setExportingFmt(null);
    }
  };

  return (
    <aside
      className={`artifact-canvas-panel ${isExpanded ? 'is-expanded' : ''} theme-${currentTheme}`}
      style={{
        '--canvas-accent': themeObj.accent,
        '--canvas-accent-bg': themeObj.accentBg,
        '--canvas-border': themeObj.border,
        '--canvas-header-bg': themeObj.headerBg,
        '--canvas-header-text': themeObj.headerText,
        '--canvas-highlight': themeObj.highlight
      }}
    >
      {/* Canvas Top Bar */}
      <header className="canvas-header">
        <div className="canvas-header-left">
          <div className="canvas-type-badge">
            <FileText size={13} />
            <span>Artifact</span>
          </div>
          <h2 className="canvas-title" title={artifact.title}>{artifact.title || 'Generated Report'}</h2>
        </div>

        <div className="canvas-header-center">
          {/* View Mode Toggle */}
          <div className="canvas-toggle-group">
            <button
              type="button"
              className={`canvas-toggle-btn ${viewMode === 'preview' ? 'active' : ''}`}
              onClick={() => setViewMode('preview')}
              title="Rendered Document Preview"
            >
              <Eye size={12} />
              <span>Preview</span>
            </button>
            <button
              type="button"
              className={`canvas-toggle-btn ${viewMode === 'code' ? 'active' : ''}`}
              onClick={() => setViewMode('code')}
              title="Raw Markdown Code"
            >
              <Code2 size={12} />
              <span>Markdown</span>
            </button>
          </div>

          {/* Theme Selector */}
          <div className="canvas-theme-selector">
            <Palette size={12} className="canvas-theme-icon" />
            <select
              value={currentTheme}
              onChange={(e) => handleThemeChange(e.target.value)}
              className="canvas-theme-select"
              title="Choose Document Design Palette"
            >
              <option value="navy">Navy Slate</option>
              <option value="emerald">Corporate Emerald</option>
              <option value="blue">Royal Blue</option>
              <option value="burgundy">Classic Crimson</option>
            </select>
          </div>
        </div>

        <div className="canvas-header-right">
          {/* Download Pills */}
          <div className="canvas-export-pills">
            <button
              type="button"
              className="canvas-export-btn"
              onClick={() => handleExport('excel')}
              disabled={exportingFmt === 'excel'}
              title="Download as Excel Sheet (.xlsx)"
            >
              {exportingFmt === 'excel' ? <RefreshCw size={12} className="spin" /> : <FileSpreadsheet size={12} />}
              <span>Excel</span>
            </button>
            <button
              type="button"
              className="canvas-export-btn"
              onClick={() => handleExport('word')}
              disabled={exportingFmt === 'word'}
              title="Download as Word Memo (.docx)"
            >
              {exportingFmt === 'word' ? <RefreshCw size={12} className="spin" /> : <FileText size={12} />}
              <span>Word</span>
            </button>
            <button
              type="button"
              className="canvas-export-btn primary"
              onClick={() => handleExport('pdf')}
              disabled={exportingFmt === 'pdf'}
              title="Download as Publication PDF (.pdf)"
            >
              {exportingFmt === 'pdf' ? <RefreshCw size={12} className="spin" /> : <FileDown size={12} />}
              <span>PDF</span>
            </button>
          </div>

          <button
            type="button"
            className="canvas-icon-btn"
            onClick={() => setIsExpanded(!isExpanded)}
            title={isExpanded ? 'Collapse canvas' : 'Expand canvas'}
          >
            {isExpanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>

          <button
            type="button"
            className="canvas-icon-btn close-btn"
            onClick={onClose}
            title="Close canvas"
          >
            <X size={15} />
          </button>
        </div>
      </header>

      {/* Canvas Main Body */}
      <div className="canvas-body-scroll">
        {viewMode === 'preview' ? (
          <div className="canvas-document-paper">
            {/* Visual Corporate Header Banner */}
            <div className="canvas-doc-banner">
              <div className="canvas-banner-stripe" />
              <div className="canvas-banner-content">
                <span className="canvas-banner-kicker">CONFIDENTIAL BRIEFING MEMO</span>
                <h1 className="canvas-banner-title">{artifact.title}</h1>
                <div className="canvas-banner-meta">
                  <span>Scope: {scope}</span>
                  <span>•</span>
                  <span>Theme: {themeObj.name}</span>
                  <span>•</span>
                  <span>Generated by SmartExtractor AI</span>
                </div>
              </div>
            </div>

            {/* Rendered Document Content */}
            <div className="canvas-rendered-markdown">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  table: ({ children }) => (
                    <div className="canvas-table-wrapper">
                      <table>{children}</table>
                    </div>
                  ),
                  blockquote: ({ children }) => (
                    <div className="canvas-callout-box">
                      {children}
                    </div>
                  )
                }}
              >
                {artifact.content}
              </ReactMarkdown>
            </div>
          </div>
        ) : (
          <div className="canvas-raw-code-view">
            <div className="canvas-code-actions">
              <button type="button" className="canvas-copy-code-btn" onClick={handleCopy}>
                {copied ? <Check size={12} color="var(--ok)" /> : <Copy size={12} />}
                <span>{copied ? 'Copied' : 'Copy Markdown'}</span>
              </button>
            </div>
            <pre className="canvas-code-block">
              <code>{artifact.content}</code>
            </pre>
          </div>
        )}
      </div>
    </aside>
  );
}
