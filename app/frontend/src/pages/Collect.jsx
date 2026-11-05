import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { api } from '../api';
import StepHeader from '../components/StepHeader';
import StatusBadge from '../components/StatusBadge';
import AgentEvidence from '../components/AgentEvidence';
import { StepTabs, QueueFilters, Queue, Detail, Decided, AllClear, filterQueue, queueCounts, RUNNING } from '../components/StepKit';

const short = (p) => (p || '').split('/').slice(-3).join('/');

// Step 1: Needs review = the feeds that did not arrive complete (the source re-sends; the day re-runs with the file - demo: header icon);
// Browse source feeds = every source file of the day, the records loaded into Bronze and the feed's trailing 5-day median.
export default function Collect({ date }) {
  const [tab, setTab] = useState('review');
  const [data, setData] = useState(null);
  const [sel, setSel] = useState(null);
  const [filter, setFilter] = useState({ state: 'open' });
  const [msg, setMsg] = useState('');
  const [run, setRun] = useState({});
  const load = useCallback(() => { if (date) api.wbCollect(date).then(setData).catch((e) => setMsg(e.message)); }, [date]);
  const loadRun = useCallback(() => { if (date) api.wbRerunStatus(date).then(setRun).catch(() => {}); }, [date]);
  useEffect(() => { setSel(null); setData(null); setMsg(''); load(); loadRun(); }, [date, load, loadRun]);
  useEffect(() => { if (!RUNNING.includes(run.state)) return undefined; const t = setInterval(loadRun, 15000); return () => clearInterval(t); }, [run.state, loadRun]);
  useEffect(() => { if (run.result === 'SUCCESS') load(); }, [run.result, load]);
  const running = RUNNING.includes(run.state);
  const bronze = Object.fromEntries((data?.feeds || []).map((f) => [f.feed, f]));
  const mon = data?.monitor || [];
  const queue = useMemo(() => mon.filter((m) => m.status !== 'PASS').map((m) => ({ ...m, s: 'review' })), [mon]);
  const shown = filterQueue(queue, filter, null);
  const item = queue.find((m) => m.feed === sel) || shown[0];
  const counts = queueCounts(queue);
  return (
    <div className="space-y-4">
      <StepHeader n={1} date={date}>
        Each source system lands a daily extract in the landing volume; Lakeflow loads it into a Bronze table, exactly as received. A feed below 90%
        of its trailing 5-day median is flagged WARNING, below 80% or missing FAIL.
      </StepHeader>
      {msg && <div className="text-xs text-blue-700">{msg}</div>}
      <StepTabs tabs={[['review', `Needs review (${counts.open})`], ['feeds', 'Browse source feeds']]} tab={tab} setTab={setTab}>
        {run?.state && <span className="text-xs text-slate-500">last re-run: <b>{running ? run.state.toLowerCase() : (run.result || run.state).toLowerCase()}</b></span>}
      </StepTabs>

      {tab === 'review' && !data && <div className="text-sm text-slate-500">Loading...</div>}
      {tab === 'review' && data && (queue.length === 0 ? <AllClear>Nothing to review: all {mon.length} feeds arrived and loaded completely.</AllClear> : (<>
        <QueueFilters filter={filter} setFilter={(f) => { setFilter(f); setSel(null); }} counts={counts} search={false} />
        {filter.state === 'open' && counts.open === 0
          ? <AllClear>Nothing left to review: {counts.done} decided - see Decided.</AllClear>
          : (
          <Queue items={shown} keyOf={(m) => m.feed} sel={item?.feed} setSel={setSel} noun="feed"
            row={(m) => [m.status, m.feed, `${m.records} records vs median ${m.expected_records != null ? Math.round(m.expected_records) : '--'}`]}>
            {item && (
              <Detail tag={item.status} title={`Feed ${item.feed} is incomplete`} s={item.s} sub={`raw.${item.feed} | ${short(bronze[item.feed]?.landing_files) || 'no file received'}`}>
                <div className="text-sm text-slate-800">{item.details}</div>
                <Decided>The tables this feed populates are provisional until it arrives complete. Ask the source system to re-send the feed; when
                  the file arrives, the day re-runs with it (Lakeflow loads it into Bronze) and the feed clears here.</Decided>
                <AgentEvidence date={date} kind="feed" refKey={item.feed} />
              </Detail>)}
          </Queue>)}
      </>))}

      {tab === 'feeds' && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
          <table className="w-full text-sm">
            <thead className="text-xs text-slate-500 bg-slate-50"><tr>
              <th className="text-left px-5 py-2">Source feed</th><th className="text-left">File received</th><th className="text-left">Bronze table</th>
              <th className="text-right">Files</th><th className="text-right">Records loaded</th><th className="text-right">5-day median</th>
              <th className="text-right">vs median</th><th className="text-center pr-5">Completeness</th></tr></thead>
            <tbody>{mon.map((m) => (
              <tr key={m.feed} className="border-t border-slate-100">
                <td className="px-5 py-2 font-semibold">{m.feed}</td>
                <td className="font-mono text-xs text-slate-500">{short(bronze[m.feed]?.landing_files) || (m.files ? '' : 'not received')}</td>
                <td className="font-mono text-xs">raw.{m.feed}</td>
                <td className="text-right">{m.files}</td><td className="text-right">{m.records}</td>
                <td className="text-right">{m.expected_records != null ? Math.round(m.expected_records) : '--'}</td>
                <td className="text-right">{m.ratio != null ? `${(parseFloat(m.ratio) * 100).toFixed(0)}%` : '--'}</td>
                <td className="text-center pr-5"><StatusBadge status={m.status} /></td>
              </tr>))}</tbody>
          </table>
        </div>)}
    </div>
  );
}
