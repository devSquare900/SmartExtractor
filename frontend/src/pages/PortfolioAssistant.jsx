import { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Send, Trash2, Copy, Check, ExternalLink,
  FileText, Plus, Clock, X
} from 'lucide-react';
import { API_BASE_URL, errorMessage } from '../api';
import { useToast } from '../components/toastContext';
import ArtifactCard from '../features/artifacts/ArtifactCard';
import ArtifactCanvas from '../features/artifacts/ArtifactCanvas';
import { parseArtifact } from '../features/artifacts/artifactUtils';
import './portfolio.css';

function formatMarkdownContent(raw) {
  if (!raw) return '';
  // Automatically normalize unlinked `(doc:uuid)` citations into clickable markdown links
  return raw.replace(/([^\n\]]+)\s*\(doc:([a-f0-9-]+)\)/gi, (match, prefix, docId) => {
    const cleanedText = prefix.replace(/^[•\s\-\*]+/, '').replace(/[*_]/g, '').trim();
    const label = cleanedText || 'View Contract';
    return `• [${label}](doc:${docId})`;
  });
}

function PortfolioMarkdown({ content, navigate }) {
  if (!content) return null;
  const processedContent = formatMarkdownContent(content);

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children }) => {
          if (href && href.startsWith('doc:')) {
            const targetDocId = href.slice(4);
            return (
              <button
                type="button"
                className="portfolio-doc-link-pill"
                onClick={() => navigate(`/documents/${targetDocId}`)}
                title="Open contract review"
              >
                <FileText size={12} className="doc-link-icon" />
                <span>{children}</span>
                <ExternalLink size={11} className="doc-link-arrow" />
              </button>
            );
          }
          return (
            <a href={href} target="_blank" rel="noopener noreferrer" className="portfolio-link">
              {children}
            </a>
          );
        },
        table: ({ children }) => (
          <div className="fresh-table-wrapper">
            <table>{children}</table>
          </div>
        )
      }}
    >
      {processedContent}
    </ReactMarkdown>
  );
}

export default function PortfolioAssistant({ navigate, documents = [], online = true }) {
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(() => {
    return localStorage.getItem('smart_extractor_portfolio_session') || 'default';
  });
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [copiedId, setCopiedId] = useState(null);
  const [activeArtifact, setActiveArtifact] = useState(null);
  const { notify } = useToast();

  const scrollRef = useRef(null);
  const textareaRef = useRef(null);
  const abortControllerRef = useRef(null);
  const isUserScrolledUpRef = useRef(false);

  // Load list of all sessions
  const loadSessions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/chat/portfolio/sessions`);
      if (res.ok) {
        const data = await res.json();
        setSessions(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error('Failed to load portfolio sessions:', err);
    }
  }, []);

  // Load chat history for the active session
  const loadHistory = useCallback(async (sessionId) => {
    try {
      const url = sessionId
        ? `${API_BASE_URL}/chat/portfolio?session_id=${encodeURIComponent(sessionId)}`
        : `${API_BASE_URL}/chat/portfolio`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setMessages(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error('Failed to load portfolio chat history:', err);
    }
  }, []);

  // Load sessions on mount
  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // Load history whenever active session changes
  useEffect(() => {
    loadHistory(currentSessionId);
    if (currentSessionId) {
      localStorage.setItem('smart_extractor_portfolio_session', currentSessionId);
    }
  }, [currentSessionId, loadHistory]);

  // Track user scroll position
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    isUserScrolledUpRef.current = distanceToBottom > 80;
  }, []);

  // Auto-scroll when new content arrives
  useEffect(() => {
    if (!isUserScrolledUpRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingContent]);

  // Create a brand new clean audit conversation
  const handleNewChat = async () => {
    if (isStreaming) return;
    setActiveArtifact(null);
    try {
      const res = await fetch(`${API_BASE_URL}/chat/portfolio/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Conversation' })
      });
      if (res.ok) {
        const newSession = await res.json();
        setCurrentSessionId(newSession.session_id);
        setMessages([]);
        setStreamingContent('');
        setIsDrawerOpen(false);
        loadSessions();
        setTimeout(() => textareaRef.current?.focus(), 60);
        return;
      }
    } catch (err) {
      console.error('Failed to create new session:', err);
    }

    const fallbackSid = `s_${Date.now().toString(36)}`;
    setCurrentSessionId(fallbackSid);
    setMessages([]);
    setStreamingContent('');
    setIsDrawerOpen(false);
    setTimeout(() => textareaRef.current?.focus(), 60);
  };

  const handleSelectSession = (sid) => {
    if (isStreaming || sid === currentSessionId) {
      setIsDrawerOpen(false);
      return;
    }
    setActiveArtifact(null);
    setCurrentSessionId(sid);
    setIsDrawerOpen(false);
  };

  const handleDeleteSession = async (e, sid) => {
    e.stopPropagation();
    if (!window.confirm('Delete this audit conversation?')) return;
    try {
      await fetch(`${API_BASE_URL}/chat/portfolio/sessions/${encodeURIComponent(sid)}`, {
        method: 'DELETE'
      });
      if (sid === currentSessionId) {
        handleNewChat();
      } else {
        loadSessions();
      }
    } catch (err) {
      console.error('Failed to delete session:', err);
    }
  };

  const handleSend = async (customPrompt) => {
    const query = (customPrompt || input).trim();
    if (!query || isStreaming) return;

    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';

    // Add user message to UI
    const userMsg = {
      id: `usr-${Date.now()}`,
      role: 'user',
      content: query,
      created_at: new Date().toISOString()
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);
    setStreamingContent('');
    isUserScrolledUpRef.current = false;

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await fetch(`${API_BASE_URL}/chat/portfolio`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: query, session_id: currentSessionId }),
        signal: controller.signal
      });

      if (!response.ok) {
        throw new Error(`Server returned HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let accumulated = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (raw === '[DONE]') break;

          try {
            const parsed = JSON.parse(raw);
            if (parsed.delta) {
              accumulated += parsed.delta;
              setStreamingContent(accumulated);
              const p = parseArtifact(accumulated);
              if (p.hasArtifact && p.artifact) {
                setActiveArtifact(p.artifact);
              }
            } else if (parsed.error) {
              accumulated += `\n\n*Error: ${parsed.error}*`;
              setStreamingContent(accumulated);
            }
          } catch {
            // Ignore parse hiccups
          }
        }
      }

      if (accumulated.trim()) {
        const assistantMsg = {
          id: `asst-${Date.now()}`,
          role: 'assistant',
          content: accumulated.trim(),
          created_at: new Date().toISOString()
        };
        setMessages((prev) => [...prev, assistantMsg]);
        const p = parseArtifact(accumulated.trim());
        if (p.hasArtifact && p.artifact) {
          setActiveArtifact(p.artifact);
        }
        loadSessions(); // Updates auto-generated title in sidebar
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setMessages((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            role: 'assistant',
            content: `I encountered an issue connecting to the portfolio intelligence service: ${err.message}`,
            created_at: new Date().toISOString()
          }
        ]);
      }
    } finally {
      setIsStreaming(false);
      setStreamingContent('');
      abortControllerRef.current = null;
      setTimeout(() => textareaRef.current?.focus(), 50);
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
          scope: 'Portfolio Intelligence Report',
        }),
      });

      if (!res.ok) {
        throw new Error(`Export failed (${res.status})`);
      }

      const disp = res.headers.get('Content-Disposition') || '';
      const match = disp.match(/filename="?([^";]+)"?/);
      const ext = format === 'excel' ? 'xlsx' : format === 'word' ? 'docx' : 'pdf';
      const filename = match ? match[1] : `Portfolio_Analysis_Report.${ext}`;

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

  const handleClear = async () => {
    if (isStreaming) return;
    if (messages.length > 0 && !window.confirm('Clear conversation in this audit session?')) return;
    setActiveArtifact(null);

    try {
      const url = currentSessionId
        ? `${API_BASE_URL}/chat/portfolio?session_id=${encodeURIComponent(currentSessionId)}`
        : `${API_BASE_URL}/chat/portfolio`;
      await fetch(url, { method: 'DELETE' });
      setMessages([]);
      setStreamingContent('');
      loadSessions();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="portfolio-page">
      {/* Top Bar Harmonized with SmartExtractor */}
      <header className="portfolio-header">
        <div className="portfolio-header-left">
          <div className="assistant-brand-mark" aria-hidden="true">
            <span />
            <span />
            <span className="hl" />
          </div>
          <div>
            <div className="portfolio-header-title-row">
              <h1 className="portfolio-header-title">Smart Assistant</h1>
              <span className="fresh-pulse-badge">
                <span className="pulse-dot" />
                {documents.length || 70} Contracts Live
              </span>
            </div>
            <div className="portfolio-header-meta">
              Search, compare, and analyze agreements across your database.
            </div>
          </div>
        </div>

        <div className="portfolio-header-actions">
          <button
            type="button"
            className="portfolio-header-btn portfolio-new-chat-btn"
            onClick={handleNewChat}
            disabled={isStreaming}
            title="Start fresh conversation with zero context baggage"
          >
            <Plus size={14} />
            <span>New Chat</span>
          </button>

          <button
            type="button"
            className="portfolio-header-btn portfolio-history-toggle-btn"
            onClick={() => setIsDrawerOpen(true)}
            title="View past conversations"
          >
            <Clock size={14} />
            <span>History</span>
          </button>

          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={handleClear}
            disabled={messages.length === 0 || isStreaming}
            title="Clear current conversation messages"
          >
            <Trash2 size={14} />
            <span>Clear</span>
          </button>
        </div>
      </header>

      {/* Main Chat Body & Split Canvas (Claude / ChatGPT Style) */}
      <div className="portfolio-body">
        <div className={`portfolio-chat-pane ${activeArtifact ? 'has-active-canvas' : ''}`}>
          <div
            className="portfolio-messages-scroll"
            ref={scrollRef}
            onScroll={handleScroll}
          >
            <div className="portfolio-thread-wrapper">
              {messages.length === 0 && !isStreaming ? (
                <div className="portfolio-hero-empty">
                  <div className="assistant-brand-mark lg" aria-hidden="true">
                    <span />
                    <span />
                    <span className="hl" />
                  </div>
                  <h2 className="portfolio-hero-title">Smart Assistant</h2>
                </div>
              ) : (
                <>
                  {messages.map((msg) => (
                    <div key={msg.id} className={`portfolio-turn ${msg.role === 'user' ? 'is-user' : 'is-asst'}`}>
                      {msg.role === 'user' ? (
                        <div className="portfolio-user-turn">
                          <div className="portfolio-user-bubble">
                            <span className="portfolio-user-text">{msg.content}</span>
                          </div>
                        </div>
                      ) : (() => {
                        const parsed = parseArtifact(msg.content);
                        const displayContent = parsed.hasArtifact ? parsed.chatText : msg.content;
                        return (
                          <div className="portfolio-asst-row">
                            <div className="assistant-brand-mark sm" aria-hidden="true">
                              <span />
                              <span />
                              <span className="hl" />
                            </div>
                            <div className="portfolio-asst-content">
                              <div className="portfolio-asst-body">
                                {displayContent && (
                                  <PortfolioMarkdown content={displayContent} navigate={navigate} />
                                )}
                                {parsed.hasArtifact && parsed.artifact && (
                                  <ArtifactCard
                                    artifact={parsed.artifact}
                                    isActive={activeArtifact?.id === parsed.artifact.id}
                                    onOpen={(art) => setActiveArtifact(art)}
                                  />
                                )}
                              </div>
                              <div className="portfolio-asst-footer">
                                <button
                                  type="button"
                                  className="portfolio-action-btn"
                                  onClick={() => handleCopy(displayContent || msg.content, msg.id)}
                                  title="Copy response"
                                >
                                  {copiedId === msg.id ? (
                                    <>
                                      <Check size={13} color="var(--ok)" />
                                      <span style={{ color: 'var(--ok)' }}>Copied</span>
                                    </>
                                  ) : (
                                    <>
                                      <Copy size={13} />
                                      <span>Copy</span>
                                    </>
                                  )}
                                </button>
                              </div>
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  ))}

                  {isStreaming && (() => {
                    const streamParsed = parseArtifact(streamingContent);
                    const displayStream = streamParsed.hasArtifact ? streamParsed.chatText : streamingContent;
                    return (
                      <div className="portfolio-turn is-asst">
                        <div className="portfolio-asst-row">
                          <div className="assistant-brand-mark sm pulse" aria-hidden="true">
                            <span />
                            <span />
                            <span className="hl" />
                          </div>
                          <div className="portfolio-asst-content">
                            <div className="portfolio-asst-body">
                              {streamingContent ? (
                                <>
                                  {displayStream && (
                                    <PortfolioMarkdown content={displayStream} navigate={navigate} />
                                  )}
                                  {streamParsed.hasArtifact && streamParsed.artifact && (
                                    <ArtifactCard
                                      artifact={streamParsed.artifact}
                                      isActive={true}
                                      onOpen={(art) => setActiveArtifact(art)}
                                    />
                                  )}
                                  <span className="enterprise-streaming-cursor" aria-hidden="true" />
                                </>
                              ) : (
                                <div className="portfolio-thinking-pill">
                                  <span className="pulse-dot" />
                                  <span>Auditing contracts & synthesizing clauses across repository...</span>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </>
              )}
            </div>
          </div>

          {/* Floating Composer Capsule (Claude/ChatGPT Style) */}
          <div className="portfolio-composer-dock">
            <div className="portfolio-composer-capsule">
              <textarea
                ref={textareaRef}
                className="portfolio-textarea"
                rows={1}
                placeholder="Ask anything about agreements, expiry dates, liabilities, payment terms..."
                value={input}
                disabled={isStreaming}
                onChange={(e) => {
                  setInput(e.target.value);
                  e.target.style.height = 'auto';
                  e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
                }}
                onKeyDown={handleKeyDown}
              />
              <button
                type="button"
                className="portfolio-send-btn"
                onClick={() => handleSend()}
                disabled={!input.trim() || isStreaming}
                title="Send query"
              >
                <Send size={15} />
              </button>
            </div>
            <div className="portfolio-composer-hint">
              <span>Grounding queries across {documents.length || 70} agreements · Press <strong>Enter</strong> to send, <strong>Shift + Enter</strong> for line break</span>
            </div>
          </div>
        </div>

        {/* Side Canvas Panel (45% split view) */}
        {activeArtifact && (
          <ArtifactCanvas
            artifact={activeArtifact}
            onClose={() => setActiveArtifact(null)}
            scope="Portfolio Intelligence Report"
            onUpdateTheme={(newTheme) => {
              setActiveArtifact((prev) => (prev ? { ...prev, theme: newTheme } : null));
            }}
          />
        )}
      </div>

      {/* Session History Drawer */}
      {isDrawerOpen && (
        <>
          <div
            className="portfolio-drawer-backdrop"
            onClick={() => setIsDrawerOpen(false)}
            aria-hidden="true"
          />
          <div className="portfolio-history-drawer" role="dialog" aria-label="History">
            <div className="portfolio-drawer-header">
              <h3 className="portfolio-drawer-title">
                <Clock size={16} color="var(--brand)" />
                <span>History</span>
              </h3>
              <button
                type="button"
                className="portfolio-drawer-close-btn"
                onClick={() => setIsDrawerOpen(false)}
                title="Close drawer"
              >
                <X size={16} />
              </button>
            </div>

            <div className="portfolio-drawer-actions">
              <button
                type="button"
                className="portfolio-drawer-new-btn"
                onClick={handleNewChat}
              >
                <Plus size={15} />
                <span>+ New Chat</span>
              </button>
            </div>

            <div className="portfolio-sessions-list">
              {sessions.length === 0 ? (
                <div className="portfolio-sessions-empty">
                  No past conversations yet.
                </div>
              ) : (
                sessions.map((s) => (
                  <div
                    key={s.session_id}
                    className={`portfolio-session-item ${s.session_id === currentSessionId ? 'is-active' : ''}`}
                    onClick={() => handleSelectSession(s.session_id)}
                  >
                    <div className="portfolio-session-main">
                      <div className="portfolio-session-title" title={s.title}>
                        {s.title || 'Conversation'}
                      </div>
                      <div className="portfolio-session-meta">
                        {s.updated_at && (
                          <span>{new Date(s.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="portfolio-session-del-btn"
                      onClick={(e) => handleDeleteSession(e, s.session_id)}
                      title="Delete session"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
