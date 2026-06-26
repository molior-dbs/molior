/**
 * ProjectForm — port of ProjectCreateDialogComponent / project.form.html.
 * Used for both Create and Edit.
 */
import React, { useState } from 'react';
import { createProject, editProject } from '../../api/projects';

export default function ProjectForm({ project, onClose }) {
  const isEdit = !!project;

  const [name, setName]               = useState(project?.name ?? '');
  const [description, setDescription] = useState(project?.description ?? '');
  const [busy, setBusy]               = useState(false);
  const [error, setError]             = useState('');

  // name: 2+ chars, letters/digits/hyphens only (mirrors nameValidator)
  const nameValid = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(name) && name.length >= 2;
  const canSave   = isEdit ? true : nameValid;

  async function save() {
    setBusy(true); setError('');
    try {
      if (isEdit) {
        await editProject(project.id, description);
      } else {
        await createProject(name.trim(), description.trim());
      }
      onClose(true);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1" style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered">
        <div className="modal-content">

          <div className="modal-header">
            <h5 className="modal-title d-flex align-items-center gap-2">
              <i className="bi bi-collection" />
              {isEdit ? 'Edit Project' : 'Create Project'}
            </h5>
            <button className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>

          <div className="modal-body">
            {error && <div className="alert alert-danger py-2">{error}</div>}

            <div className="mb-3">
              <label className="form-label fw-semibold">Project Name</label>
              <input
                className="form-control"
                value={name}
                readOnly={isEdit}
                disabled={isEdit}
                onChange={e => setName(e.target.value)}
                autoFocus
              />
              {!isEdit && name.length > 0 && !nameValid && (
                <div className="form-text text-danger">
                  Name must be ≥2 chars and contain only letters, digits, dots, hyphens or underscores.
                </div>
              )}
            </div>

            <div className="mb-3">
              <label className="form-label fw-semibold">Description</label>
              <textarea
                className="form-control"
                rows={3}
                maxLength={255}
                value={description}
                onChange={e => setDescription(e.target.value)}
              />
            </div>
          </div>

          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" onClick={save} disabled={busy || !canSave}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}
              Ok
            </button>
          </div>

        </div>
      </div>
    </div>
  );
}
