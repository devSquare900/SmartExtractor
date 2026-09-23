import { STATUS, displayStatus } from '../lib/status';

export default function StatusBadge({ doc, status }) {
  const key = status || displayStatus(doc);
  const meta = STATUS[key];
  return (
    <span className={`badge badge-${meta.tone} ${meta.processing ? 'badge-processing' : ''}`}>
      <span className="dot" />
      {meta.label}
    </span>
  );
}
