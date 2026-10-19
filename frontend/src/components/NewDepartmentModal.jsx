import { useState } from 'react';
import { X, FolderPlus, Sparkles, AlertCircle } from 'lucide-react';
import { createDepartment } from '../api';

const PRESET_COLORS = [
  { label: 'Blue', hex: '#2563eb' },
  { label: 'Purple', hex: '#7c3aed' },
  { label: 'Cyan', hex: '#0891b2' },
  { label: 'Emerald', hex: '#059669' },
  { label: 'Amber', hex: '#d97706' },
  { label: 'Rose', hex: '#e11d48' },
  { label: 'Slate', hex: '#475569' },
];

export default function NewDepartmentModal({ isOpen, onClose, onCreated }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState(PRESET_COLORS[0].hex);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) {
      setError('Please enter a department name.');
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const res = await createDepartment({
        name: name.trim(),
        description: description.trim(),
        color,
      });
      if (onCreated) onCreated(res.data);
      setName('');
      setDescription('');
      onClose();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to create department.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="dept-modal-backdrop" onClick={onClose}>
      <div className="dept-modal card rise" onClick={(e) => e.stopPropagation()}>
        <div className="dept-modal-header">
          <div className="dept-modal-title">
            <div className="dept-modal-icon" style={{ background: `${color}20`, color }}>
              <FolderPlus size={18} />
            </div>
            <div>
              <h3>Create Category</h3>
              <p>Organize contracts by business or service domain.</p>
            </div>
          </div>
          <button className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="dept-modal-form">
          {error && (
            <div className="dept-modal-error">
              <AlertCircle size={15} />
              <span>{error}</span>
            </div>
          )}

          <div className="dept-form-group">
            <label htmlFor="dept-name">Category Name</label>
            <input
              id="dept-name"
              type="text"
              className="input"
              placeholder="e.g. Cybersecurity, Hardware Infrastructure"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              required
            />
          </div>

          <div className="dept-form-group">
            <label htmlFor="dept-desc">Scope & Description</label>
            <textarea
              id="dept-desc"
              className="input"
              rows={2}
              placeholder="e.g. SOC audits, vulnerability management, security tool subscriptions"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <div className="dept-form-group">
            <label>Color Accent</label>
            <div className="dept-colors-row">
              {PRESET_COLORS.map((c) => (
                <button
                  key={c.hex}
                  type="button"
                  className={`dept-color-swatch ${color === c.hex ? 'active' : ''}`}
                  style={{ background: c.hex }}
                  onClick={() => setColor(c.hex)}
                  title={c.label}
                  aria-label={c.label}
                />
              ))}
            </div>
          </div>

          <div className="dept-modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? 'Creating...' : 'Create Category'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
