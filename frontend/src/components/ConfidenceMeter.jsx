import { confidenceTone } from '../lib/status';

export default function ConfidenceMeter({ value, threshold = 0.85, width }) {
  if (value == null) return <span className="meter muted">—</span>;
  return (
    <span className={`meter ${confidenceTone(value, threshold)}`} title="Average OCR confidence">
      <span className="meter-track" style={width ? { width } : undefined}>
        <span className="meter-fill" style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      {Math.round(value * 100)}%
    </span>
  );
}
