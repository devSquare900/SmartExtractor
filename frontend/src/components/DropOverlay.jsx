import { useEffect, useRef, useState } from 'react';
import { UploadCloud } from 'lucide-react';

// Full-window drop target shown while files are dragged over the app.
export default function DropOverlay({ onFiles }) {
  const [active, setActive] = useState(false);
  const depth = useRef(0);

  useEffect(() => {
    const onEnter = (e) => {
      if (Array.from(e.dataTransfer?.types || []).includes('Files')) {
        setActive(true);
      }
    };
    const onOver = (e) => {
      if (Array.from(e.dataTransfer?.types || []).includes('Files')) {
        e.preventDefault();
        setActive(true);
      }
    };
    const onLeave = (e) => {
      if (!e.relatedTarget) {
        setActive(false);
      }
    };
    const onDrop = (e) => {
      e.preventDefault();
      setActive(false);
      if (e.dataTransfer?.files?.length) onFiles(e.dataTransfer.files);
    };
    const forceClose = () => setActive(false);

    window.addEventListener('dragenter', onEnter);
    window.addEventListener('dragover', onOver);
    window.addEventListener('dragleave', onLeave);
    window.addEventListener('drop', onDrop);
    window.addEventListener('close-drop-overlay', forceClose);
    return () => {
      window.removeEventListener('dragenter', onEnter);
      window.removeEventListener('dragover', onOver);
      window.removeEventListener('dragleave', onLeave);
      window.removeEventListener('drop', onDrop);
      window.removeEventListener('close-drop-overlay', forceClose);
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
