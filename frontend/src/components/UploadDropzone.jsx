import { useState } from 'react';
import { UploadCloud } from 'lucide-react';

export default function UploadDropzone({ onBrowse, onFiles, compact = false }) {
  const [over, setOver] = useState(false);
  const [dropped, setDropped] = useState(false);

  const onDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setOver(false);
    window.dispatchEvent(new Event('close-drop-overlay'));
    if (e.dataTransfer.files?.length) {
      setDropped(true);
      onFiles(e.dataTransfer.files);
      setTimeout(() => setDropped(false), 2000);
    }
  };

  return (
    <div
      className={`dropzone ${over ? 'over' : ''} ${compact ? 'compact' : ''}`}
      onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      onClick={onBrowse}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onBrowse())}
    >
      <div className="paper-stack" aria-hidden="true">
        <span className="sheet s3" />
        <span className="sheet s2" />
        <span className="sheet s1">
          <i /><i /><i className="hl" /><i />
        </span>
      </div>
      <div className="dropzone-text">
        <strong>{over ? 'Release to upload' : (dropped ? 'Uploaded successfully' : 'Drop contracts & invoices here')}</strong>
        <span>
          or <u>browse files</u> · PDF, PNG, JPG, TIFF · up to 25 MB each
        </span>
      </div>
      {!dropped && <span className="dropzone-icon"><UploadCloud size={20} /></span>}
    </div>
  );
}
