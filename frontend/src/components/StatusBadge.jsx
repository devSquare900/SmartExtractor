import { STATUS, displayStatus } from '../lib/status';

export default function StatusBadge({ doc, status, variant = 'badge' }) {
  const key = status || displayStatus(doc);
  const meta = STATUS[key] || { tone: 'muted', label: key };

  if (variant === 'dot') {
    return (
      <span className={`status-dot-item tone-${meta.tone}`} title={meta.label}>
        <span className={`status-dot-bullet ${meta.processing ? 'pulse' : ''}`} />
        <span className="status-dot-label">{meta.label}</span>
      </span>
    );
  }

  return (
    <span className={`badge badge-${meta.tone} ${meta.processing ? 'badge-processing' : ''}`}>
      <span className="dot" />
      {meta.label}
    </span>
  );
}
