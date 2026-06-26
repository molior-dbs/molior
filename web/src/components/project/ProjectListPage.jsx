/**
 * ProjectListPage — port of ProjectListComponent + project-list.html.
 *
 * Columns: name · # versions · # builds · # CI builds · description · actions
 * Actions: Details · Edit · Delete
 * Header:  ⊕ Create button
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchProjects, deleteProject } from '../../api/projects';
import ProjectForm from './ProjectForm';
import ConfirmModal from '../build/ConfirmModal';

const PRIMARY  = '#571845';
const TH       = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 25;

export default function ProjectListPage() {
  const navigate = useNavigate();

  const [projects, setProjects] = useState([]);
  const [total, setTotal]       = useState(null);
  const [error, setError]       = useState('');
  const [page, setPage]         = useState(1);
  const [filterName, setFilterName] = useState('');

  // modal: { type: 'create' | 'edit' | 'delete', project? }
  const [modal, setModal] = useState(null);

  const load = useCallback(async (pg = page) => {
    setError(''); setTotal(null);
    try {
      const data = await fetchProjects({ q: filterName, page: pg, page_size: PAGE_SIZE });
      setProjects(data.results ?? []);
      setTotal(data.total_result_count ?? 0);
    } catch (e) { setError(e.message); setTotal(-1); }
  }, [page, filterName]);

  useEffect(() => { load(page); }, [page]);

  const prevFilterRef = useRef(filterName);
  useEffect(() => {
    if (prevFilterRef.current !== filterName) {
      prevFilterRef.current = filterName;
      setPage(1); load(1);
    }
  }, [filterName]);

  function closeModal(reload) { setModal(null); if (reload) load(page); }

  const totalPages = total > 0 ? Math.ceil(total / PAGE_SIZE) : 1;

  function handleWheel(e) {
    if (e.ctrlKey) return;
    if (e.deltaY > 0 && page < totalPages) setPage(p => p + 1);
    else if (e.deltaY < 0 && page > 1)    setPage(p => p - 1);
  }

  return (
    <div className="p-3" onWheel={handleWheel}>

      {/* ── Modals ── */}
      {modal?.type === 'create' && <ProjectForm onClose={closeModal} />}
      {modal?.type === 'edit'   && <ProjectForm project={modal.project} onClose={closeModal} />}
      {modal?.type === 'delete' && (
        <ConfirmModal
          title="Delete Project"
          body="The project will be deleted if no project versions exist. This operation cannot be undone."
          onConfirm={() => deleteProject(modal.project.name)}
          onClose={closeModal}
        />
      )}

      <h1 className="mb-3 d-flex align-items-center gap-2" style={{ fontSize: 24, fontWeight: 500 }}>
        <i className="bi bi-collection" />Projects
      </h1>

      <div>
        <table className="table table-sm table-hover align-middle mb-0" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              {/* Name / filter */}
              <th style={{ ...TH, minWidth: 220 }}>
                <input
                  className="form-control form-control-sm bg-transparent border-0 text-white"
                  placeholder="Name"
                  value={filterName}
                  onChange={e => setFilterName(e.target.value)}
                  style={{ minWidth: 180 }}
                />
              </th>
              <th style={{ ...TH, textAlign: 'center', whiteSpace: 'nowrap' }}># Versions</th>
              <th style={{ ...TH, textAlign: 'center', whiteSpace: 'nowrap' }}># Builds</th>
              <th style={{ ...TH, textAlign: 'center', whiteSpace: 'nowrap' }}># CI Builds</th>
              <th style={{ ...TH, width: '100%' }}>Description</th>
              {/* Create button */}
              <th style={{ ...TH, textAlign: 'right' }}>
                <button
                  className="btn btn-sm border-0 p-0"
                  style={{ color: 'white', fontSize: 20, lineHeight: 1 }}
                  title="Create project"
                  onClick={() => setModal({ type: 'create' })}
                >⊕</button>
              </th>
            </tr>
          </thead>
          <tbody>
            {total === null && (
              <tr><td colSpan={6} className="text-center py-3 text-muted">Loading…</td></tr>
            )}
            {total === -1 && (
              <tr><td colSpan={6} className="text-center py-3 text-danger">Unable to load data ({error})</td></tr>
            )}
            {total === 0 && (
              <tr><td colSpan={6} className="text-center py-3 text-muted">No entries found</td></tr>
            )}

            {projects.map(p => (
              <tr key={p.id} style={{ cursor: 'pointer' }}
                onClick={() => navigate(`/project/${p.name}`)}>

                <td><strong>{p.name}</strong></td>

                <td className="text-center">
                  {p.projectversionCount > 0 && p.projectversionCount}
                </td>
                <td className="text-center">
                  {p.buildCount > 0 && p.buildCount}
                </td>
                <td className="text-center">
                  {p.cibuildCount > 0 && p.cibuildCount}
                </td>

                <td className="text-muted">{p.description}</td>

                {/* Actions */}
                <td className="text-end" onClick={e => e.stopPropagation()}>
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary"
                      data-bs-toggle="dropdown">
                      <i className="bi bi-three-dots-vertical" />
                    </button>
                    <ul className="dropdown-menu dropdown-menu-end">
                      <li>
                        <button className="dropdown-item"
                          onClick={() => navigate(`/project/${p.name}`)}>
                          <i className="bi bi-list me-2" />Details
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item"
                          onClick={() => setModal({ type: 'edit', project: p })}>
                          <i className="bi bi-pencil me-2" />Edit
                        </button>
                      </li>
                      <li>
                        <button className="dropdown-item text-danger"
                          onClick={() => setModal({ type: 'delete', project: p })}>
                          <i className="bi bi-trash me-2" />Delete
                        </button>
                      </li>
                    </ul>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Pagination ── */}
      <div className="d-flex justify-content-between align-items-center mt-2 px-1" style={{ fontSize: 13 }}>
        <span className="text-muted">
          {total > 0 ? `${(page - 1) * PAGE_SIZE + 1}–${Math.min(page * PAGE_SIZE, total)} of ${total}` : ''}
        </span>
        <nav>
          <ul className="pagination pagination-sm mb-0">
            <li className={`page-item ${page <= 1 ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => setPage(1)}>&laquo;</button>
            </li>
            <li className={`page-item ${page <= 1 ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => setPage(p => p - 1)}>&lsaquo;</button>
            </li>
            <li className="page-item disabled">
              <span className="page-link">{page} / {totalPages}</span>
            </li>
            <li className={`page-item ${page >= totalPages ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => setPage(p => p + 1)}>&rsaquo;</button>
            </li>
            <li className={`page-item ${page >= totalPages ? 'disabled' : ''}`}>
              <button className="page-link" onClick={() => setPage(totalPages)}>&raquo;</button>
            </li>
          </ul>
        </nav>
      </div>
    </div>
  );
}
