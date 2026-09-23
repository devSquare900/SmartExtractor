import { useEffect, useRef, useState } from 'react';
import { UploadCloud } from 'lucide-react';

// Full-window drop target shown while files are dragged over the app.
export default function DropOverlay({ onFiles }) {
  const [active, setActive] = useState(false);
  const depth = useRef(0);

  useEffect(() => {
    const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes('Files');
    const onEnter = (e) => {
      if (!hasFiles(e)) return;
      depth.current += 1;
      setActive(true);
    };
    const onLeave = (e) => {
      if (!hasFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setActive(false);
    };
    const onOver = (e) => hasFiles(e) && e.preventDefault();
    const onDrop = (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setActive(false);
      if (e.dataTransfer.files?.length) onFiles(e.dataTransfer.files);
    };
    window.addEventListener('dragenter', onEnter);
    window.addEventListener('dragleave', onLeave);
    window.addEventListener('dragover', onOver);
    window.addEventListener('drop', onDrop);
    return () => {
      window.removeEventListener('dragenter', onEnter);
      window.removeEventListener('dragleave', onLeave);
      window.removeEventListener('dragover', onOver);
      window.removeEventListener('drop', onDrop);
    };
  }, [onFiles]);

  if (!active) return null;
  return (
    <div className="drop-overlay">
      <div className="drop-overlay-card">
        <UploadCloud size={34} />
        <strong className="display">Drop to extract</strong>
        <span>Files are uploaded and processed right away.</span>
      </div>
    </div>
  );
}
