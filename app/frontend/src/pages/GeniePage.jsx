import React from 'react';
import { Sparkles, ExternalLink } from 'lucide-react';

// Genie: the FR 2052a Genie Agent embedded as it is in Databricks (Share -> Embed agent). It answers from the Unity Catalog metric
// views (the governed semantic layer) and the detail tables, shows its SQL, charts and follow-ups, and runs as the signed-in user,
// so each person sees only the data they may see.
export default function GeniePage({ date, embedUrl, genieUrl }) {
  return (
    <div className="flex flex-col h-[calc(100vh-7rem)] gap-3">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-navy-900 flex items-center gap-2"><Sparkles className="w-5 h-5" /> Genie</h1>
          <p className="text-sm text-slate-500 mt-1">
            Ask about the filing in plain English{date ? <> - name the date, e.g. "What is the LCR per entity on {date}?"</> : null}. Genie answers from
            the governed metric views and the detail tables, and shows the SQL it ran.
          </p>
        </div>
        {genieUrl && <a href={genieUrl} target="_blank" rel="noopener noreferrer" className="text-xs text-blue-700 hover:underline flex items-center gap-1 shrink-0">
          Open in Databricks <ExternalLink className="w-3 h-3" /></a>}
      </div>
      {embedUrl
        ? <iframe title="FR 2052a Genie Agent" src={embedUrl} allow="clipboard-write" className="flex-1 w-full bg-white rounded-xl border border-slate-200" style={{ border: 0 }} />
        : <div className="text-sm text-slate-500">Loading...</div>}
    </div>
  );
}
