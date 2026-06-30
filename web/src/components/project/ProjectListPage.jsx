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
import ContextMenu from '../common/ContextMenu';
import Pagination from '../common/Pagination';

const PRIMARY  = '#571845';
const TH       = { backgroundColor: PRIMARY, color: 'white' };
const PAGE_SIZE = 20;

export default function ProjectListPage() {
  const navigate = useNavigate();

  const [projects, setProjects] = useState([]);
  const [total, setTotal]       = useState(null);
  const [error, setError]       = useState('');
  const [page, setPage]         = useState(1);
  const [filterName, setFilterName] = useState('');

  // modal: { type: 'create' | 'edit' | 'delete', project? }
  const [modal, setModal] = useState(null);
  const [ctxMenu, setCtxMenu] = useState(null);

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

  return (
    <div className="p-3">

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

      {ctxMenu && (
        <ContextMenu x={ctxMenu.x} y={ctxMenu.y} onClose={() => setCtxMenu(null)}>
          <li><button className="dropdown-item" onClick={() => { navigate(`/project/${ctxMenu.p.name}`); setCtxMenu(null); }}><i className="bi bi-list me-2" />Details</button></li>
          <li><button className="dropdown-item" onClick={() => { setModal({ type: 'edit', project: ctxMenu.p }); setCtxMenu(null); }}><i className="bi bi-pencil me-2" />Edit</button></li>
          <li><button className="dropdown-item text-danger" onClick={() => { setModal({ type: 'delete', project: ctxMenu.p }); setCtxMenu(null); }}><i className="bi bi-trash me-2" />Delete</button></li>
        </ContextMenu>
      )}

      <h1 className="mb-3 d-flex align-items-center gap-2" style={{ fontSize: 24, fontWeight: 500 }}>
        <i className="bi bi-collection" />Projects
      </h1>

      <Pagination page={page} totalPages={totalPages} total={total} pageSize={PAGE_SIZE}
                  onPageChange={setPage} label="projects" />

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
                onClick={e => { if (!e.target.closest('.dropdown')) navigate(`/project/${p.name}`); }}
                onContextMenu={e => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, p }); }}>

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
                <td className="text-end">
                  <div className="dropdown">
                    <button className="btn btn-sm btn-link p-0 text-secondary"
                      data-bs-toggle="dropdown" onClick={e => e.stopPropagation()}>
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


    </div>
  );
}
