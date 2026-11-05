import React, { useState, useEffect } from 'react';
import { BarChart3, ExternalLink, ChevronDown, ChevronRight } from 'lucide-react';

let cached = null;
const info = () => (cached ||= fetch('/api/workspace-url').then((r) => r.json()));

// The FR 2052a AI/BI dashboard page for this step, embedded: charts and full-volume tables straight from Delta through the
// SQL warehouse. Set the as-of date (and entity) in the dashboard's own filters.
export default function DashboardEmbed({ page, title, height = 900, open: startOpen = true, dashboard = 'main' }) {
  const [d, setD] = useState(null);
  const [open, setOpen] = useState(startOpen);
  useEffect(() => { info().then(setD).catch(() => {}); }, []);
  const id = dashboard === 'lcr' ? d?.lcr_dashboard_id : d?.dashboard_id;   // the main FR 2052a dashboard, or the LCR module's own
  if (!id) return null;
  const src = `${d.url}/embed/dashboardsv3/${id}/pages/${page}?o=${d.workspace_id}`;
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
      <div className="px-4 py-2.5 border-b border-slate-100 flex items-center gap-2">
        <button onClick={() => setOpen(!open)} className="flex items-center gap-2 text-sm font-semibold text-navy-900">
          {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}<BarChart3 className="w-4 h-4 text-blue-600" />{title}</button>
        <span className="text-[11px] text-slate-400">Databricks AI/BI dashboard - all positions, straight from Delta; choose the as-of date in its filter</span>
        <a href={`${d.url}/dashboardsv3/${id}/published/pages/${page}`} target="_blank" rel="noopener noreferrer" className="ml-auto flex items-center gap-1 text-xs text-blue-700 hover:underline">
          Open in Databricks <ExternalLink className="w-3.5 h-3.5" /></a>
      </div>
      {open && <iframe title={title} src={src} className="w-full rounded-b-xl" style={{ height, border: 0 }} />}
    </div>
  );
}
