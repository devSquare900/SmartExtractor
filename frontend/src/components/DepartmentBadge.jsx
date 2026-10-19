import { useState, useRef, useEffect } from 'react';
import { 
  Building2, Cloud, Network, Code2, Folder, ChevronDown, 
  Sparkles, Check, Plus, RefreshCw, Layers 
} from 'lucide-react';
import { updateDocumentDepartment, classifyDocumentDepartment } from '../api';

export const DEPARTMENT_THEMES = {
  'Data Center': {
    icon: Building2,
    color: '#2563eb',
    bg: 'rgba(37, 99, 235, 0.12)',
    border: 'rgba(37, 99, 235, 0.28)',
    text: '#3b82f6'
  },
  'Cloud Services': {
    icon: Cloud,
    color: '#9333ea',
    bg: 'rgba(147, 51, 234, 0.12)',
    border: 'rgba(147, 51, 234, 0.28)',
    text: '#a855f7'
  },
  'Network & Telecom': {
    icon: Network,
    color: '#0891b2',
    bg: 'rgba(8, 145, 178, 0.12)',
    border: 'rgba(8, 145, 178, 0.28)',
    text: '#06b6d4'
  },
  'Software & SaaS': {
    icon: Code2,
    color: '#059669',
    bg: 'rgba(5, 150, 105, 0.12)',
    border: 'rgba(5, 150, 105, 0.28)',
    text: '#10b981'
  },
  'General': {
    icon: Folder,
    color: '#6b7280',
    bg: 'rgba(107, 114, 128, 0.12)',
    border: 'rgba(107, 114, 128, 0.25)',
    text: '#9ca3af'
  }
};

export function getDepartmentTheme(deptName) {
  if (DEPARTMENT_THEMES[deptName]) {
    return DEPARTMENT_THEMES[deptName];
  }
  return {
    icon: Layers,
    color: '#6366f1',
    bg: 'rgba(99, 102, 241, 0.12)',
    border: 'rgba(99, 102, 241, 0.25)',
    text: '#818cf8'
  };
}

export default function DepartmentBadge({
  department = 'General',
  docId,
  departments = [],
  onDepartmentChanged,
  onOpenCreateModal,
  interactive = true,
  size = 'md', // 'sm' | 'md'
  variant = 'badge', // 'badge' | 'minimal'
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const menuRef = useRef(null);

  const theme = getDepartmentTheme(department);
  const IconComponent = theme.icon;

  useEffect(() => {
    if (!open) return;
    const handleOutsideClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('pointerdown', handleOutsideClick);
    return () => document.removeEventListener('pointerdown', handleOutsideClick);
  }, [open]);

  const handleSelect = async (e, deptName) => {
    e.stopPropagation();
    setOpen(false);
    if (!docId || deptName === department) return;
    setLoading(true);
    try {
      await updateDocumentDepartment(docId, deptName);
      if (onDepartmentChanged) onDepartmentChanged(deptName);
    } catch (err) {
      console.error('Failed to change department:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleReclassify = async (e) => {
    e.stopPropagation();
    if (!docId) return;
    setLoading(true);
    try {
      const res = await classifyDocumentDepartment(docId);
      const newDept = res.data?.department || 'General';
      if (onDepartmentChanged) onDepartmentChanged(newDept);
    } catch (err) {
      console.error('Failed to classify department:', err);
    } finally {
      setLoading(false);
      setOpen(false);
    }
  };

  const defaultList = ['Data Center', 'Cloud Services', 'General'];
  const allDeptNames = departments.length > 0 
    ? Array.from(new Set(departments.map((d) => d.name)))
    : defaultList;

  if (!interactive) {
    return (
      <div 
        className={variant === 'minimal'
          ? 'dept-plain'
          : `dept-badge ${size === 'sm' ? 'dept-badge-sm' : ''}`}
        style={variant === 'minimal' ? undefined : {
          background: theme.bg,
          color: theme.text,
          borderColor: theme.border,
        }}
        title={`Category: ${department}`}
      >
        <IconComponent size={variant === 'minimal' ? 14 : 12} style={{ color: theme.color, flexShrink: 0 }} />
        <span className={variant === 'minimal' ? 'dept-plain-name' : 'dept-name'}>{department}</span>
      </div>
    );
  }

  return (
    <div 
      className="dept-badge-wrap" 
      ref={menuRef} 
      style={{ position: 'relative', display: 'inline-block' }}
      onClick={(e) => interactive && e.stopPropagation()}
    >
      <button
        type="button"
        disabled={!interactive || loading}
        onClick={(e) => {
          if (!interactive) return;
          e.stopPropagation();
          setOpen((prev) => !prev);
        }}
        className={variant === 'minimal'
          ? `dept-plain ${interactive ? 'dept-plain-interactive' : ''}`
          : `dept-badge ${size === 'sm' ? 'dept-badge-sm' : ''} ${interactive ? 'dept-badge-interactive' : ''}`}
        style={variant === 'minimal' ? undefined : {
          background: theme.bg,
          color: theme.text,
          borderColor: theme.border,
        }}
        title={interactive ? `Category: ${department} (Click to change)` : `Category: ${department}`}
      >
        {loading ? (
          <RefreshCw size={variant === 'minimal' ? 13 : 12} className="spin" />
        ) : (
          <IconComponent size={variant === 'minimal' ? 14 : 12} style={{ color: theme.color, flexShrink: 0 }} />
        )}
        <span className={variant === 'minimal' ? 'dept-plain-name' : 'dept-name'}>{department}</span>
        {interactive && <ChevronDown size={11} className={variant === 'minimal' ? 'dept-plain-chevron' : 'dept-chevron'} />}
      </button>

      {open && interactive && (
        <div className="dept-menu-popover card rise" style={{ zIndex: 1100 }}>
          <div className="dept-menu-header">
            <span>Assign Category</span>
            {loading && <RefreshCw size={12} className="spin" />}
          </div>
          <div className="dept-menu-list">
            {allDeptNames.map((dName) => {
              const dTheme = getDepartmentTheme(dName);
              const DIcon = dTheme.icon;
              const isSelected = dName.toLowerCase() === department.toLowerCase();
              return (
                <button
                  key={dName}
                  type="button"
                  className={`dept-menu-item ${isSelected ? 'active' : ''}`}
                  onClick={(e) => handleSelect(e, dName)}
                >
                  <DIcon size={14} style={{ color: dTheme.color }} />
                  <span className="dept-item-label">{dName}</span>
                  {isSelected && <Check size={14} className="dept-check" />}
                </button>
              );
            })}
          </div>

          <div className="dept-menu-divider" />

          {docId && (
            <button
              type="button"
              className="dept-menu-action"
              onClick={handleReclassify}
              title="Forensic AI scans recitals, scope of work, and pricing to re-classify"
            >
              <Sparkles size={14} color="#f59e0b" />
              <span>Forensic AI Re-classify</span>
            </button>
          )}

          {onOpenCreateModal && (
            <button
              type="button"
              className="dept-menu-action"
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                onOpenCreateModal();
              }}
            >
              <Plus size={14} />
              <span>New Category...</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
