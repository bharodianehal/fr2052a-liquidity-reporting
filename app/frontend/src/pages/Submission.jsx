import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import StatusBadge from '../components/StatusBadge';
import StepHeader from '../components/StepHeader';
import { FileCode2, CheckCircle2, XCircle, Send, Download, CalendarClock, ShieldAlert } from 'lucide-react';

const STATUS_STYLE = {
  READY_FOR_REVIEW: 'bg-amber-50 text-amber-700 border-amber-200',
  BLOCKED: 'bg-red-50 text-red-700 border-red-200',
  APPROVED: 'bg-blue-50 text-blue-700 border-blue-200',
  REJECTED: 'bg-red-50 text-red-700 border-red-200',
  SUBMITTED: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  OVERRIDE_REQUESTED: 'bg-purple-50 text-purple-700 border-purple-200',
  REPORTING_REQUESTED: 'bg-slate-50 text-slate-700 border-slate-200',
};

const num = (v, d = 0) => (v == null ? '--' : parseFloat(v).toLocaleString('en-US', { maximumFractionDigits: d }));

export default function Submission({ date, embedded, onLoad, canApprove }) {
  const [sub, setSub] = useState(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    if (!date) return;
    api.getSubmission(date).then((d) => { setSub(d); onLoad?.(d); }).catch((e) => setError(e.message));
  }, [date, onLoad]);
  useEffect(() => { load(); }, [load]);

  const act = async (action) => {
    setBusy(true); setError('');
    try {
      await api.reviewSubmission(date, action, note);
      setNote('');
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!sub) return <div className="text-sm text-slate-500">Loading submission for {date}...</div>;
  if (sub.run_number == null) return <div className="text-sm text-slate-500">No 6G submission has been generated for {date}. Run the pipeline first.</div>;

  const status = sub.status || 'READY_FOR_REVIEW';

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between text-sm">
        <p className="text-slate-500">
          {(sub.entities || []).map((e) => e.entity_id).join(' + ')} in one file | reporter {sub.entity?.reporter_ticker} ({sub.entity?.listing_exchange}) |
          6G header version {sub.version}{sub.released_by ? ` | generated for release by ${sub.released_by}, ${String(sub.generated_at).replace('T', ' ').slice(0, 16)}` : ''}
        </p>
        <span className={`px-3 py-1.5 rounded-lg border text-sm font-semibold ${STATUS_STYLE[status] || ''}`}>{status.replace(/_/g, ' ')}</span>
      </div>
      <p className="text-xs text-slate-500 flex items-center gap-1"><CalendarClock className="w-3.5 h-3.5" />Primary due {sub.due.primary} ({sub.entity?.primary_timing}); Reduced due {sub.due.reduced} ({sub.entity?.reduced_timing}).</p>
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-5 py-3 border-b border-slate-100 text-sm font-semibold text-navy-900">Files</div>
        <table className="w-full text-sm">
          <thead className="text-xs text-slate-500 bg-slate-50">
            <tr><th className="text-left px-5 py-2">File</th><th className="text-left">Schedule</th><th className="text-right">Report types</th>
              <th className="text-right">Records</th><th className="text-center">XSD</th><th className="text-left pl-4">First XSD error</th><th /></tr>
          </thead>
          <tbody>
            {sub.files.map((f) => (
              <tr key={f.file_type} className="border-t border-slate-100">
                <td className="px-5 py-2 font-mono text-xs flex items-center gap-2"><FileCode2 className="w-4 h-4 text-blue-600" />{f.file_name}</td>
                <td>{f.file_type}</td>
                <td className="text-right">{f.report_types || '--'}</td>
                <td className="text-right">{num(f.record_count)}</td>
                <td className="text-center"><StatusBadge status={f.xsd_valid ? 'PASS' : 'FAIL'} /></td>
                <td className="pl-4 text-xs text-red-700">{f.xsd_error_sample || ''}</td>
                <td className="pr-5 text-right">
                  <a href={api.downloadSubmissionFile(date, f.file_type, f.run_number)} className="inline-flex items-center gap-1 text-xs text-blue-700 hover:underline">
                    <Download className="w-3.5 h-3.5" /> XML</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-3">
        <h3 className="text-sm font-semibold text-navy-900">Sign-off</h3>
        <p className="text-xs text-slate-500">
          The approver approves the files generated for release; a different person marks them submitted once they are transmitted to
          the FRS 6G SFTP folder (four eyes). Files with ERROR failures or XSD errors are BLOCKED: fix them in Validate and generate again,
          or request an override with a documented reason that someone else approves. A generation after submission carries the next
          6G header version (a resubmission).
        </p>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Note (required to reject or request an override)"
          className="w-full border border-slate-200 rounded-lg p-2 text-sm" />
        <div className="flex flex-wrap gap-2">
          <button disabled={busy || !['READY_FOR_REVIEW', 'OVERRIDE_REQUESTED'].includes(status) || !canApprove || !sub.released_by} onClick={() => act('APPROVED')}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 text-white disabled:opacity-40">
            <CheckCircle2 className="w-4 h-4" /> Approve</button>
          <button disabled={busy || status !== 'BLOCKED'} onClick={() => act('OVERRIDE_REQUESTED')}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-purple-600 text-white disabled:opacity-40">
            <ShieldAlert className="w-4 h-4" /> Request override</button>
          <button disabled={busy || !['READY_FOR_REVIEW', 'APPROVED', 'BLOCKED', 'OVERRIDE_REQUESTED'].includes(status)} onClick={() => act('REJECTED')}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-red-600 text-white disabled:opacity-40">
            <XCircle className="w-4 h-4" /> Reject</button>
          <button disabled={busy || status !== 'APPROVED'} onClick={() => act('SUBMITTED')}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium bg-emerald-600 text-white disabled:opacity-40">
            <Send className="w-4 h-4" /> Mark submitted</button>
        </div>
        {error && <div className="text-xs text-red-600">{error}</div>}
        <table className="w-full text-xs mt-2">
          <thead className="text-slate-500"><tr><th className="text-left">When</th><th className="text-left">Action</th>
            <th className="text-left">By</th><th className="text-left">Note</th></tr></thead>
          <tbody>{sub.review_log.map((r, k) => (
            <tr key={k} className="border-t border-slate-100">
              <td className="py-1">{String(r.action_timestamp).replace('T', ' ').slice(0, 19)}</td>
              <td className="font-semibold">{r.action}{r.action === 'GENERATED' ? ` (${r.status})` : ''}</td><td>{r.actor}</td><td>{r.note}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}
