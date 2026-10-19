import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Send, X, User, Plus,
  Check, Copy, Maximize2, Minimize2,
  PanelLeftClose, PanelLeftOpen
} from 'lucide-react';
import { API_BASE_URL, errorMessage } from '../../api';
import { useToast } from '../../components/toastContext';
import ArtifactCard from '../artifacts/ArtifactCard';
import ArtifactCanvas from '../artifacts/ArtifactCanvas';
import { parseArtifact } from '../artifacts/artifactUtils';
import './chatbot.css';

// Enterprise AST-based Markdown Formatter
// Compliant with CommonMark + GitHub Flavored Markdown (GFM)
function FormattedMessage({ content }) {
  if (!content) return null;

  // Sanitize: strip any raw [Page X] markers as requested, and normalize legacy blockquotes
  const sanitizedContent = content
    .replace(/`?(?:\[|【)Page\s*\d+[^\]】]*(?:\]|】)`?/gi, '')
    .replace(/^(?:>\s*-\s*|>-|-\s*>)\s*/gm, '- ');

  return (
    <div className="fresh-body-flow">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h2 className="fresh-h1">{children}</h2>,
          h2: ({ children }) => <h3 className="fresh-h2">{children}</h3>,
          h3: ({ children }) => <h4 className="fresh-h3">{children}</h4>,
          h4: ({ children }) => <h5 className="fresh-h4">{children}</h5>,
          p: ({ children }) => {
            // Check for legal risk alerts [HIGH RISK], [MEDIUM RISK], [LOW RISK], or ⚠️
            const raw = Array.isArray(children)
              ? children.map((c) => (typeof c === 'string' ? c : '')).join('')
              : (typeof children === 'string' ? children : '');

            if (
              raw.includes('[HIGH RISK]') ||
              raw.includes('[MEDIUM RISK]') ||
              raw.includes('[LOW RISK]') ||
              raw.startsWith('⚠️')
            ) {
              let riskType = 'med';
              if (raw.includes('[HIGH RISK]') || raw.startsWith('⚠️')) riskType = 'high';
              else if (raw.includes('[LOW RISK]')) riskType = 'low';

              return (
                <div className={`fresh-alert-card alert-${riskType}`}>
                  <div className="alert-badge">
                    {riskType === 'high' ? 'HIGH RISK' : riskType === 'med' ? 'MEDIUM RISK' : 'NOTICE'}
                  </div>
                  <div className="alert-text">{children}</div>
                </div>
              );
            }
            return <p className="fresh-p">{children}</p>;
          },
          ul: ({ children }) => <ul className="fresh-ul">{children}</ul>,
          ol: ({ children }) => <ol className="fresh-ol">{children}</ol>,
          li: ({ children }) => <li className="fresh-li">{children}</li>,
          strong: ({ children }) => <strong className="fresh-strong">{children}</strong>,
          em: ({ children }) => <em className="fresh-em">{children}</em>,
          code: ({ children, ...props }) => (
            <code className="fresh-inline-code" {...props}>
              {children}
            </code>
          ),
          blockquote: ({ children }) => (
            <blockquote className="fresh-blockquote">{children}</blockquote>
          ),
          table: ({ children }) => (
            <div className="fresh-table-wrapper">
              <table className="fresh-table">{children}</table>
            </div>
          ),
        }}
      >
        {sanitizedContent}
      </ReactMarkdown>
    </div>
  );
}

export default function DocumentAssistant({
  doc,
  documentTitle,
  open,
  onClose,
  onJumpToPage,
  currentPage = 1,
  isWide: controlledIsWide,
  onToggleWide,
  isFocusMode = false,
  onToggleFocus,
}) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [internalIsWide, setInternalIsWide] = useState(false);
  const isWide = controlledIsWide !== undefined ? controlledIsWide : internalIsWide;
  const notify = useToast();
  const [copiedId, setCopiedId] = useState(null);
  const [activeArtifact, setActiveArtifact] = useState(null);

  const feedRef = useRef(null);
  const threadEndRef = useRef(null);
  const textareaRef = useRef(null);
  const abortControllerRef = useRef(null);
  const isUserScrolledUp = useRef(false);

  const docId = doc?.doc_id;
  const docTitle = documentTitle || doc?.summary?.title || doc?.contract_name?.value || doc?.filename || 'Untitled document';

  const handleFeedScroll = useCallback(() => {
    if (!feedRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = feedRef.current;
    // Detect if user deliberately scrolled up to read past history
    isUserScrolledUp.current = (scrollHeight - scrollTop - clientHeight) > 80;
  }, []);

  const scrollToBottom = useCallback((smooth = false) => {
    if (!feedRef.current) return;
    if (smooth) {
      feedRef.current.scrollTo({
        top: feedRef.current.scrollHeight,
        behavior: 'smooth',
      });
    } else {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, []);

  const handleExport = async (content, format, msgId) => {
    const key = `${msgId}-${format}`;
    setExportingKey(key);
    try {
      const msgIndex = messages.findIndex((m) => m.id === msgId);
      const prevUserMsg = msgIndex > 0 ? messages.slice(0, msgIndex).reverse().find((m) => m.role === 'user') : null;
      const query = prevUserMsg?.content || '';

      const res = await fetch(`${API_BASE_URL}/chat/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          format,
          query,
          scope: docTitle || 'Contract Analysis',
        }),
      });

      if (!res.ok) {
        throw new Error(`Export failed (${res.status})`);
      }

      const disp = res.headers.get('Content-Disposition') || '';
      const match = disp.match(/filename="?([^";]+)"?/);
      const ext = format === 'excel' ? 'xlsx' : format === 'word' ? 'docx' : 'pdf';
      const filename = match ? match[1] : `SmartExtractor_Report.${ext}`;

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      notify(`Downloaded ${format.toUpperCase()} report!`, 'success');
    } catch (err) {
      console.error(err);
      notify(errorMessage(err, 'Failed to export document'), 'error');
    } finally {
      setExportingKey(null);
    }
  };

  // Fetch past messages from backend database
  useEffect(() => {
    if (!open || !docId) return;

    let cancelled = false;
    fetch(`${API_BASE_URL}/documents/${docId}/chat`)
      .then((res) => {
        if (!res.ok) throw new Error('Failed to load history');
        return res.json();
      })
      .then((data) => {
        if (!cancelled) {
          setMessages(Array.isArray(data) ? data : []);
          setTimeout(() => scrollToBottom(false), 60);
        }
      })
      .catch((err) => {
        console.error(err);
      });

    return () => {
      cancelled = true;
    };
  }, [open, docId, scrollToBottom]);

  // Jitter-free stream pinning: direct scrollTop assignment without smooth animation fights
  useEffect(() => {
    if (isStreaming && !isUserScrolledUp.current && feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [streamingContent, isStreaming]);

  // Message list update (user message added or history loaded)
  useEffect(() => {
    if (open && !isStreaming) {
      scrollToBottom(messages.length > 0);
    }
  }, [messages.length, open, isStreaming, scrollToBottom]);

  // Focus textarea when opened
  useEffect(() => {
    if (open) {
      setTimeout(() => textareaRef.current?.focus(), 150);
    }
  }, [open]);


  // Handle send message & streaming
  const handleSend = async (queryText) => {
    const text = (queryText || input).trim();
    if (!text || !docId || isStreaming) return;

    setInput('');
    setIsStreaming(true);
    setStreamingContent('');

    const userMsg = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await fetch(`${API_BASE_URL}/documents/${docId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let accumulated = '';
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data:')) continue;

          const dataStr = trimmed.slice(5).trim();
          if (dataStr === '[DONE]') break;

          try {
            const parsed = JSON.parse(dataStr);
            if (parsed.delta) {
              accumulated += parsed.delta;
              setStreamingContent(accumulated);
              const p = parseArtifact(accumulated);
              if (p.hasArtifact && p.artifact) {
                setActiveArtifact(p.artifact);
              }
            } else if (parsed.error) {
              accumulated += `\n\n⚠️ ${parsed.error}`;
              setStreamingContent(accumulated);
            }
          } catch (e) {}
        }
      }

      if (accumulated.trim()) {
        const asstMsg = {
          id: `asst-${Date.now()}`,
          role: 'assistant',
          content: accumulated.trim(),
          created_at: new Date().toISOString(),
        };
        setMessages((prev) => [...prev, asstMsg]);
        const p = parseArtifact(accumulated.trim());
        if (p.hasArtifact && p.artifact) {
          setActiveArtifact(p.artifact);
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setMessages((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            role: 'assistant',
            content: `I ran into an issue connecting to the AI engine: ${err.message}`,
            created_at: new Date().toISOString(),
          },
        ]);
      }
    } finally {
      setIsStreaming(false);
      setStreamingContent('');
      abortControllerRef.current = null;
      setTimeout(() => textareaRef.current?.focus(), 80);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleCopy = (text, id) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const handleClearHistory = async () => {
    if (!docId || isStreaming) return;
    if (messages.length > 0 && !window.confirm('Start a new chat for this document? Previous messages will be cleared.')) return;
    setActiveArtifact(null);

    try {
      await fetch(`${API_BASE_URL}/documents/${docId}/chat`, { method: 'DELETE' });
      setMessages([]);
      setStreamingContent('');
      setTimeout(() => textareaRef.current?.focus(), 80);
    } catch (e) {
      console.error(e);
    }
  };

  if (!open) return null;

  return (
    <aside className={`fresh-copilot-drawer ${isWide ? 'is-wide' : ''}`} aria-label="SmartAssistant">
      {/* Soft Fresh Header */}
      <header className="fresh-header">
        <div className="fresh-header-brand">
          <span className="assistant-brand-mark sm" aria-hidden="true" title="SmartAssistant">
            <span />
            <span />
            <span className="hl" />
          </span>
          <div className="fresh-header-meta">
            <div className="fresh-title-row">
              <span className="fresh-title">SmartAssistant</span>
            </div>
            <span className="fresh-doc-subtitle" title={docTitle}>
              {docTitle}
            </span>
          </div>
        </div>

        <div className="fresh-header-controls">
          <button
            type="button"
            className="fresh-new-chat-btn"
            onClick={handleClearHistory}
            disabled={isStreaming || (messages.length === 0 && !streamingContent)}
            title="Start fresh conversation for this document"
          >
            <Plus size={13} />
            <span>New Chat</span>
          </button>

          {onToggleFocus && (
            <button
              type="button"
              className={`fresh-control-btn ${isFocusMode ? 'is-active' : ''}`}
              onClick={onToggleFocus}
              title={isFocusMode ? 'Exit Focus Mode (Show Extracted Fields)' : 'Focus Mode: Hide fields to expand PDF and AI'}
            >
              {isFocusMode ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
            </button>
          )}

          <button
            type="button"
            className="fresh-control-btn"
            onClick={toggleWide}
            title={isWide ? 'Compact View (420px)' : 'Expanded View (560px)'}
          >
            {isWide ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>

          <button
            type="button"
            className="fresh-control-btn fresh-close-btn"
            onClick={onClose}
            title="Close SmartAssistant (Esc)"
          >
            <X size={17} />
          </button>
        </div>
      </header>

      {/* Message Canvas / Feed */}
      <div className="fresh-feed" ref={feedRef} onScroll={handleFeedScroll}>
        {messages.length === 0 && !streamingContent && (
          <div className="fresh-empty-state">
            <span className="assistant-brand-mark lg" aria-hidden="true">
              <span />
              <span />
              <span className="hl" />
            </span>
            <h3 className="fresh-empty-title">Contract Intelligence Assistant</h3>
          </div>
        )}

        {/* Existing Messages */}
        {messages.map((msg) => (
          <div key={msg.id} className={`fresh-turn ${msg.role === 'user' ? 'is-user' : 'is-asst'}`}>
            {msg.role === 'user' ? (
              <div className="user-capsule">
                <div className="user-capsule-text">{msg.content}</div>
                <div className="user-capsule-avatar">
                  <User size={12} />
                </div>
              </div>
            ) : (() => {
              const parsed = parseArtifact(msg.content);
              const displayContent = parsed.hasArtifact ? parsed.chatText : msg.content;
              return (
                <>
                  <div className="asst-avatar-col">
                    <span className="assistant-brand-mark sm" aria-hidden="true">
                      <span />
                      <span />
                      <span className="hl" />
                    </span>
                  </div>
                  <div className="asst-content-col">
                    <div className="asst-message-body">
                      {displayContent && (
                        <FormattedMessage content={displayContent} onJumpToPage={onJumpToPage} />
                      )}
                      {parsed.hasArtifact && parsed.artifact && (
                        <ArtifactCard
                          artifact={parsed.artifact}
                          isActive={activeArtifact?.id === parsed.artifact.id}
                          onOpen={(art) => setActiveArtifact(art)}
                        />
                      )}
                    </div>
                    <div className="asst-footer-actions">
                      <button
                        type="button"
                        className="asst-action-btn"
                        onClick={() => handleCopy(displayContent || msg.content, msg.id)}
                        title="Copy response"
                      >
                        {copiedId === msg.id ? <Check size={12} className="ok-check" /> : <Copy size={12} />}
                        <span>{copiedId === msg.id ? 'Copied' : 'Copy'}</span>
                      </button>
                    </div>
                  </div>
                </>
              );
            })()}
          </div>
        ))}

        {/* Live Streaming Turn */}
        {isStreaming && (() => {
          const streamParsed = parseArtifact(streamingContent);
          const displayStream = streamParsed.hasArtifact ? streamParsed.chatText : streamingContent;
          return (
            <div className="fresh-turn is-asst is-live">
              <div className="asst-avatar-col">
                <span className="assistant-brand-mark sm pulse" aria-hidden="true">
                  <span />
                  <span />
                  <span className="hl" />
                </span>
              </div>
              <div className="asst-content-col">
                {!streamingContent ? (
                  <div className="asst-thinking-state" aria-live="polite">
                    <div className="thinking-shimmer-badge">
                      <span className="thinking-radar-orb">
                        <span className="radar-core" />
                        <span className="radar-wave" />
                      </span>
                      <span className="thinking-label">Searching document & analyzing clauses...</span>
                    </div>
                  </div>
                ) : (
                  <div className="asst-message-body is-streaming">
                    {displayStream && (
                      <FormattedMessage content={displayStream} onJumpToPage={onJumpToPage} />
                    )}
                    {streamParsed.hasArtifact && streamParsed.artifact && (
                      <ArtifactCard
                        artifact={streamParsed.artifact}
                        isActive={true}
                        onOpen={(art) => setActiveArtifact(art)}
                      />
                    )}
                    <span className="enterprise-streaming-cursor" aria-hidden="true" />
                  </div>
                )}
              </div>
            </div>
          );
        })()}

        <div ref={threadEndRef} />
      </div>

      {/* Fresh Floating Command Input */}
      <footer className="fresh-composer">
        <div className="fresh-input-box">
          <textarea
            ref={textareaRef}
            className="fresh-textarea"
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything about this document, audit math, or check risks..."
            disabled={isStreaming}
          />
          <div className="fresh-input-actions">
            {isStreaming ? (
              <button
                type="button"
                className="fresh-stop-btn"
                onClick={() => abortControllerRef.current?.abort()}
                title="Stop generation"
              >
                <div className="stop-square" />
              </button>
            ) : (
              <button
                type="button"
                className="fresh-send-btn"
                onClick={() => handleSend()}
                disabled={!input.trim()}
                title="Send inquiry (Enter)"
              >
                <Send size={14} />
              </button>
            )}
          </div>
        </div>
        <div className="fresh-composer-hint">
          <span>Press <b>Enter ↵</b> to send · Grounded in verified document OCR</span>
        </div>
      </footer>

      {/* Side Canvas Overlay for Document Reports */}
      {activeArtifact && (
        <div className="fresh-artifact-overlay">
          <ArtifactCanvas
            artifact={activeArtifact}
            onClose={() => setActiveArtifact(null)}
            scope={docTitle}
            onUpdateTheme={(newTheme) => {
              setActiveArtifact((prev) => (prev ? { ...prev, theme: newTheme } : null));
            }}
          />
        </div>
      )}
    </aside>
  );
}
