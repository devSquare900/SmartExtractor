import { fileKind } from '../lib/format';

const TONES = { PDF: 'pdf', PNG: 'img', JPG: 'img', TIFF: 'img' };

// A small folded-corner paper sheet with the file type on it.
export default function FileIcon({ filename, size = 40 }) {
  const kind = fileKind(filename);
  return (
    <span className={`file-icon ${TONES[kind] || ''}`} style={{ '--s': `${size}px` }} aria-hidden="true">
      <span className="file-icon-lines" />
      <span className="file-icon-tag">{kind}</span>
    </span>
  );
}
