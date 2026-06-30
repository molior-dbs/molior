/**
 * ContextMenu — lightweight right-click floating menu.
 *
 * Renders children as a positioned Bootstrap dropdown-menu at (x, y).
 * Closes on click-away, scroll, or Escape.
 *
 * Usage:
 *   const [ctx, setCtx] = useState(null); // { x, y, row }
 *
 *   <tr onContextMenu={e => { e.preventDefault(); setCtx({ x: e.clientX, y: e.clientY, row }); }}>
 *
 *   {ctx && (
 *     <ContextMenu x={ctx.x} y={ctx.y} onClose={() => setCtx(null)}>
 *       <li><button className="dropdown-item" onClick={...}>Action</button></li>
 *     </ContextMenu>
 *   )}
 */
import { useEffect } from 'react';

export default function ContextMenu({ x, y, onClose, children }) {
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onClose, true);
    window.addEventListener('resize', onClose);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onClose, true);
      window.removeEventListener('resize', onClose);
    };
  }, [onClose]);

  return (
    <>
      {/* Click-away backdrop */}
      <div style={{ position: 'fixed', inset: 0, zIndex: 1039 }} onClick={onClose} />
      <ul className="dropdown-menu show"
          style={{ position: 'fixed', top: y, left: x, zIndex: 1040 }}>
        {children}
      </ul>
    </>
  );
}
