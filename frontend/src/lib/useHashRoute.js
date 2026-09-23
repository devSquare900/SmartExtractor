import { useCallback, useEffect, useRef, useState } from 'react';

// Tiny hash router: #/, #/documents?status=review, #/documents/<id>
function parse(hash) {
  const raw = hash.replace(/^#/, '') || '/';
  const [path, queryString = ''] = raw.split('?');
  const segments = path.split('/').filter(Boolean);
  const query = Object.fromEntries(new URLSearchParams(queryString));
  if (segments[0] === 'documents' && segments[1]) return { name: 'review', docId: segments[1], query };
  if (segments[0] === 'documents') return { name: 'documents', query };
  return { name: 'overview', query };
}

/**
 * Returns [route, navigate, pendingNavigation, resolvePending].
 * While `blockRef.current` is true, navigation (including the back button) is held
 * as `pendingNavigation` until resolvePending(true|false) is called.
 */
export function useHashRoute(blockRef) {
  const [hash, setHash] = useState(() => window.location.hash || '#/');
  const [pending, setPending] = useState(null);
  const currentRef = useRef(hash);
  const bypassRef = useRef(false);

  useEffect(() => {
    const onHashChange = () => {
      const next = window.location.hash || '#/';
      if (next === currentRef.current) return;
      if (blockRef.current && !bypassRef.current) {
        window.history.replaceState(null, '', currentRef.current);
        setPending(next);
        return;
      }
      bypassRef.current = false;
      currentRef.current = next;
      setHash(next);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, [blockRef]);

  const navigate = useCallback((to) => {
    const target = to.startsWith('#') ? to : `#${to}`;
    if (target !== window.location.hash) window.location.hash = target;
  }, []);

  const resolvePending = useCallback((proceed) => {
    const target = pending;
    setPending(null);
    if (proceed && target) {
      bypassRef.current = true;
      window.location.hash = target;
    }
  }, [pending]);

  return [parse(hash), navigate, pending, resolvePending];
}
