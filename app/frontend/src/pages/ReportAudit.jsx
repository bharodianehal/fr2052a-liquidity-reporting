import React, { useEffect, useMemo, useState } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { api } from '../api';

export default function ReportAudit({ embedded }) {
  const [reviews, setReviews] = useState([]);
  const [runs, setRuns] = useState([]);
  const autoSize = useMemo(() => ({ type: 'fitCellContents' }), []);

  useEffect(() => {
    api.getSubmissionHistory().then(setReviews).catch(console.error);
    api.getPipelineRuns().then(setRuns).catch(() => setRuns([]));
  }, []);

  const reviewCols = useMemo(() => [
    { field: 'action_timestamp', headerName: 'When', valueFormatter: (p) => String(p.value || '').replace('T', ' ').slice(0, 19) },
    { field: 'as_of_date', headerName: 'As of Date' },
    { field: 'run_number', headerName: 'Run' },
    { field: 'version', headerName: '6G version', valueFormatter: (p) => `v${p.value}` },
    { field: 'action', headerName: 'Action' },
    { field: 'status', headerName: 'Status' },
    { field: 'actor', headerName: 'By' },
    { field: 'note', headerName: 'Note' },
  ], []);
  const runCols = useMemo(() => [
    { field: 'date', headerName: 'As of Date' },
    { field: 'pipeline', headerName: 'Scope' },
    { field: 'user', headerName: 'Requested by' },
    { field: 'started', headerName: 'Started' },
    { field: 'duration', headerName: 'Duration' },
    { field: 'status', headerName: 'Status' },
    { field: 'id', headerName: 'Run ID' },
  ], []);

  const grid = (rows, cols, height) => (
    <div className="ag-theme-alpine" style={{ height }}>
      <AgGridReact rowData={rows} columnDefs={cols} defaultColDef={{ sortable: true, filter: true, resizable: true }}
        autoSizeStrategy={autoSize} enableCellTextSelection pagination paginationPageSize={25} />
    </div>
  );

  return (
    <div className="space-y-5">
      {!embedded && <h1 className="text-xl font-bold text-navy-900">2052a Audit Trail</h1>}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
          <span className="text-sm font-medium text-slate-600">Reporting runs and sign-off</span>
          <span className="text-xs text-slate-400">reg_2052a.submission_review | pipeline generation, approval, rejection, submission</span>
        </div>
        {grid(reviews, reviewCols, 360)}
      </div>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between">
          <span className="text-sm font-medium text-slate-600">Pipeline runs</span>
          <span className="text-xs text-slate-400">fr2052a-daily job runs</span>
        </div>
        {grid(runs, runCols, 320)}
      </div>
    </div>
  );
}
