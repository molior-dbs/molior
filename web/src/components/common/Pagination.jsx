/**
 * Pagination — shared paginator bar used by every table.
 *
 * Renders above the table (caller places it before <table>).
 * Shows: count label on the left · first/prev/N of M/next/last on the right.
 */
export default function Pagination({ page, totalPages, total, pageSize, onPageChange, label = 'entries' }) {
  const start = total > 0 ? (page - 1) * pageSize + 1 : 0;
  const end   = total > 0 ? Math.min(page * pageSize, total) : 0;

  return (
    <div className="d-flex justify-content-between align-items-center mb-1 px-1" style={{ fontSize: 13 }}>
      <span className="text-muted">
        {total === null && 'Loading…'}
        {total === 0   && `0 ${label}`}
        {total  >  0  && <>{start}–{end} of <strong>{total}</strong> {label}</>}
      </span>
      {totalPages > 1 && (
        <nav>
          <ul className="pagination pagination-sm mb-0">
            <li className={`page-item ${page <= 1 ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => onPageChange(1)} title="First page">
                <i className="bi bi-chevron-bar-left" />
              </button>
            </li>
            <li className={`page-item ${page <= 1 ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => onPageChange(page - 1)} title="Previous page">
                <i className="bi bi-chevron-left" />
              </button>
            </li>
            <li className="page-item disabled">
              <span className="page-link">{page} / {totalPages}</span>
            </li>
            <li className={`page-item ${page >= totalPages ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => onPageChange(page + 1)} title="Next page">
                <i className="bi bi-chevron-right" />
              </button>
            </li>
            <li className={`page-item ${page >= totalPages ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => onPageChange(totalPages)} title="Last page">
                <i className="bi bi-chevron-bar-right" />
              </button>
            </li>
          </ul>
        </nav>
      )}
    </div>
  );
}
