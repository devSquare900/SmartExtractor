import { LayoutDashboard, Files, Highlighter, AlertOctagon, Upload, Sun, Moon, PanelLeftClose, PanelLeftOpen } from 'lucide-react';

export default function NavRail({ route, navigate, stats, online, theme, onToggleTheme, onUploadClick, collapsed, onToggleCollapse }) {
  const items = [
    { key: 'overview', label: 'Overview', icon: LayoutDashboard, to: '/', active: route.name === 'overview' },
    {
      key: 'documents', label: 'Documents', icon: Files, to: '/documents', count: stats.total,
      active: (route.name === 'documents' && !route.query.status) || route.name === 'review',
    },
    {
      key: 'review', label: 'Needs review', icon: Highlighter, to: '/documents?status=review', count: stats.review,
      tone: 'warn', active: route.name === 'documents' && route.query.status === 'review',
    },
    {
      key: 'failed', label: 'Failed', icon: AlertOctagon, to: '/documents?status=error', count: stats.error,
      tone: 'bad', active: route.name === 'documents' && route.query.status === 'error', hideWhenZero: true,
    },
  ];

  return (
    <aside className="nav-rail">
      <div className="brand-row">
        <a className="brand" href="#/" aria-label="SmartExtractor home">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span className="hl" />
          </span>
          <span className="brand-name">
            Smart<em>Extractor</em>
          </span>
        </a>
        <button
          className="collapse-btn"
          onClick={onToggleCollapse}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
      </div>

      <button className="btn btn-lime nav-upload" onClick={onUploadClick} title="Upload documents">
        <Upload size={17} />
        <span>Upload documents</span>
      </button>

      <nav className="nav-list" aria-label="Main">
        <span className="nav-label">Workspace</span>
        {items
          .filter((item) => !(item.hideWhenZero && !item.count))
          .map(({ key, label, icon: Icon, to, count, tone, active }) => (
            <button
              key={key}
              className={`nav-item ${active ? 'active' : ''}`}
              onClick={() => navigate(to)}
              aria-current={active ? 'page' : undefined}
              title={label}
            >
              <Icon size={18} strokeWidth={1.9} />
              <span className="nav-text">{label}</span>
              {count > 0 && <span className={`nav-count ${tone || ''}`}>{count}</span>}
            </button>
          ))}
      </nav>

      <div className="nav-foot">
        <div className={`health ${online ? 'on' : 'off'}`} title={online ? 'Backend connected' : 'Backend not reachable'}>
          <span className="health-dot" />
          <span className="nav-text">{online ? 'Engine online' : 'Engine offline'}</span>
          {stats.processing > 0 && <span className="health-meta nav-text">{stats.processing} in queue</span>}
        </div>
        <button className="nav-item theme-toggle" onClick={onToggleTheme} title={theme === 'dark' ? 'Light mode' : 'Dark mode'}>
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          <span className="nav-text">{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
        </button>
      </div>
    </aside>
  );
}
