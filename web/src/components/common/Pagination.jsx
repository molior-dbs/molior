/**
 * Pagination — shared paginator bar used by every table.
 *
 * Renders above the table (caller places it before <table>).
 * All controls right-aligned: "x–y of N label" · first · prev · p/N · next · last
 * Scroll wheel over the bar navigates pages.
 */
import { useCallback } from 'react';

const PRIMARY    = '#571845';
const NO_SELECT  = { userSelect: 'none' };

export default function Pagination({ page, totalPages, total, pageSize, onPageChange, label = 'entries' }) {
  const start = total > 0 ? (page - 1) * pageSize + 1 : 0;
  const end   = total > 0 ? Math.min(page * pageSize, total) : 0;
  const atFirst = page <= 1;
  const atLast  = page >= totalPages;

  const onWheel = useCallback(e => {
    e.preventDefault();
    if (e.deltaY < 0 && !atFirst) onPageChange(page - 1);
    if (e.deltaY > 0 && !atLast)  onPageChange(page + 1);
  }, [page, atFirst, atLast, onPageChange]);

  return (
    <div className="d-flex justify-content-end align-items-center gap-2 mb-1 px-1"
         style={{ fontSize: 13, ...NO_SELECT }}
         onWheel={onWheel}>
      <span className="text-muted">
        {total === null && 'Loading…'}
        {total === 0   && `0 ${label}`}
        {total  >  0  && <>{start}–{end} of <strong>{total}</strong> {label}</>}
      </span>
      {totalPages > 1 && (
        <>
          <button className="btn btn-sm btn-link p-0" style={{ color: PRIMARY }} disabled={atFirst}
                  onClick={() => onPageChange(1)} title="First page">
            <i className="bi bi-arrow-bar-up" />
          </button>
          <button className="btn btn-sm btn-link p-0" style={{ color: PRIMARY }} disabled={atFirst}
                  onClick={() => onPageChange(page - 1)} title="Previous page">
            <i className="bi bi-arrow-up-circle" />
          </button>
          <span className="text-muted">{page} / {totalPages}</span>
          <button className="btn btn-sm btn-link p-0" style={{ color: PRIMARY }} disabled={atLast}
                  onClick={() => onPageChange(page + 1)} title="Next page">
            <i className="bi bi-arrow-down-circle" />
          </button>
          <button className="btn btn-sm btn-link p-0" style={{ color: PRIMARY }} disabled={atLast}
                  onClick={() => onPageChange(totalPages)} title="Last page">
            <i className="bi bi-arrow-bar-down" />
          </button>
        </>
      )}
    </div>
  );
}
