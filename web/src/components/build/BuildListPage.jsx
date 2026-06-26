/**
 * BuildListPage — port of BuildListComponent + build-list.html.
 * Just a page shell around the reusable BuildTable.
 */
import React from 'react';
import BuildTable from './BuildTable';

export default function BuildListPage() {
  return (
    <div className="p-3">
      <h1 className="mb-3 d-flex align-items-center gap-2" style={{ fontSize: 24, fontWeight: 500 }}>
        <i className="bi bi-journals" />
        Builds
      </h1>
      <BuildTable />
    </div>
  );
}
