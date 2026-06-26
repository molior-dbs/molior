/**
 * Generic confirmation modal used by Delete / Abort / Rebuild actions.
 * Replaces the three Angular MatDialog components.
 */
import React, { useState } from 'react';

export default function ConfirmModal({ id, title, body, onConfirm, onClose }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function handleConfirm() {
    setBusy(true);
    setError('');
    try {
      await onConfirm();
      onClose(true);
    } catch (e) {
      setError(e.message || 'Operation failed');
      setBusy(false);
    }
  }

  return (
    <div className="modal fade show d-block" tabIndex="-1" role="dialog"
         style={{ backgroundColor: 'rgba(0,0,0,.4)' }}>
      <div className="modal-dialog modal-dialog-centered" role="document">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">{title}</h5>
            <button type="button" className="btn-close" onClick={() => onClose(false)} disabled={busy} />
          </div>
          <div className="modal-body">
            {error && <div className="alert alert-danger py-1 mb-2">{error}</div>}
            {body}
          </div>
          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={() => onClose(false)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary"   onClick={handleConfirm}        disabled={busy}>
              {busy && <span className="spinner-border spinner-border-sm me-2" />}
              Ok
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
