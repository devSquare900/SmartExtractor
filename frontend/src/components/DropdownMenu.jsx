import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

const GAP = 6;
const MARGIN = 8;

// Click-to-open menu rendered in a portal, so it is never clipped by or hidden behind cards.
// `children` is a function receiving close().
export default function DropdownMenu({ trigger, children, align = 'right', label = 'Open menu' }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const anchorRef = useRef(null);
  const menuRef = useRef(null);

  // Place below the trigger, or above it when there is no room; keep inside the viewport.
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const a = anchorRef.current?.getBoundingClientRect();
      const m = menuRef.current?.getBoundingClientRect();
      if (!a || !m) return;
      let top = a.bottom + GAP;
      if (top + m.height > window.innerHeight - MARGIN) top = Math.max(MARGIN, a.top - GAP - m.height);
      let left = align === 'right' ? a.right - m.width : a.left;
      left = Math.min(Math.max(MARGIN, left), window.innerWidth - m.width - MARGIN);
      setPos({ top, left });
    };
    place();
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', place, true);
    };
  }, [open, align]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (!anchorRef.current?.contains(e.target) && !menuRef.current?.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const toggle = () => {
    setPos(null);
    setOpen((o) => !o);
  };

  return (
    <div className="dropdown" ref={anchorRef} onClick={(e) => e.stopPropagation()}>
      {trigger({ open, toggle, label })}
      {open && createPortal(
        <div
          ref={menuRef}
          className="menu"
          role="menu"
          style={pos ? { top: pos.top, left: pos.left } : { top: 0, left: 0, visibility: 'hidden' }}
          onClick={(e) => e.stopPropagation()}
        >
          {children(() => setOpen(false))}
        </div>,
        document.body,
      )}
    </div>
  );
}
