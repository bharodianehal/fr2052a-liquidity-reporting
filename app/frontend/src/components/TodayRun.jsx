import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { stepLink } from './AgentEvidence';
import { TriangleAlert, CircleCheck } from 'lucide-react';

const IN = ['I.U', 'I.A', 'I.S', 'I.O'];
const OUT = ['O.D', 'O.O', 'O.S', 'O.W'];
const COLOR = { 'I.U': '#3B9AB2', 'I.A': '#1F6FD1', 'I.S': '#8EC5E8', 'I.O': '#C9E2F5', 'O.D': '#4B5563', 'O.O': '#9CA3AF', 'O.S': '#7C5CD6', 'O.W': '#C4B5FD' };
const bn = (v) => `$${(v || 0).toLocaleString('en-US', { maximumFractionDigits: 1, minimumFractionDigits: 1 })}B`;

// a smooth line through points (Catmull-Rom as cubic Bezier), with the control points kept between the two ends of each segment
// so a band never overshoots - it never crosses the axis or another band
function curve(pts) {
  if (!pts.length) return '';
  const clamp = (v, a, b) => Math.min(Math.max(v, Math.min(a, b)), Math.max(a, b));
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const [p0, p1, p2, p3] = [pts[i - 1] || pts[i], pts[i], pts[i + 1], pts[i + 2] || pts[i + 1]];
    const c1 = clamp(p1[1] + (p2[1] - p0[1]) / 6, p1[1], p2[1]);
    const c2 = clamp(p2[1] - (p3[1] - p1[1]) / 6, p1[1], p2[1]);
    d += ` C${p1[0] + (p2[0] - p0[0]) / 6},${c1} ${p2[0] - (p3[0] - p1[0]) / 6},${c2} ${p2[0]},${p2[1]}`;
  }
  return d;
}

// The maturity river: the whole report on one strip - inflows above the line, outflows below, by contractual maturity bucket and
// FR 2052a table (USD bn) - with the breaks pinned where their positions sit. Hover a bucket for its breakdown.
function River({ r, breaks }) {
  const nav = useNavigate();
  const [hover, setHover] = useState(null);
  const W = 1100, H = 300, L = 70, R = 20, T = 30, B = 30;
  const n = r.buckets.length, dx = (W - L - R) / (n - 1);
  const x = (i) => L + i * dx;
  const up = r.buckets.map((b) => IN.reduce((a, t) => a + r.values[b][t], 0));
  const dn = r.buckets.map((b) => OUT.reduce((a, t) => a + r.values[b][t], 0));
  const maxUp = Math.max(...up, 0.1), maxDn = Math.max(...dn, 0.1);
  const y0 = T + (H - T - B) * (maxUp / (maxUp + maxDn));
  const k = (H - T - B) / (maxUp + maxDn);
  const bands = (tables, sign) => {
    const acc = r.buckets.map(() => 0);
    return tables.map((t) => {
      const lo = acc.map((a) => a);
      r.buckets.forEach((b, i) => { acc[i] += r.values[b][t]; });
      const top = r.buckets.map((_, i) => [x(i), y0 - sign * acc[i] * k]);
      const bot = r.buckets.map((_, i) => [x(i), y0 - sign * lo[i] * k]);
      const d = `${curve(top)} L${bot[bot.length - 1][0]},${bot[bot.length - 1][1]} ${curve([...bot].reverse()).replace(/^M/, 'L')} Z`;
      const mid = r.buckets.map((_, i) => y0 - sign * (lo[i] + acc[i]) / 2 * k);
      return { t, d, mid };
    });
  };
  const ins = bands(IN, 1), outs = bands(OUT, -1);
  const pins = breaks.filter((b) => b.bucket && b.river_table && b.status === 'PROPOSED').slice(0, 6);
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" onMouseLeave={() => setHover(null)}>
        <text x={8} y={y0 - 20} className="fill-slate-400" fontSize="11">INFLOWS</text>
        <text x={8} y={y0 + 28} className="fill-slate-400" fontSize="11">OUTFLOWS</text>
        {[...ins, ...outs].map((b) => <path key={b.t} d={b.d} fill={COLOR[b.t]} opacity={0.92} />)}
        <line x1={L} x2={W - R} y1={y0} y2={y0} stroke="#11171C" strokeWidth="1.5" />
        {r.buckets.map((b, i) => (
          <g key={b} onMouseEnter={() => setHover(i)}>
            <rect x={x(i) - dx / 2} y={T} width={dx} height={H - T - B} fill={hover === i ? '#2272B4' : 'transparent'} opacity={hover === i ? 0.07 : 0} />
            <text x={x(i)} y={H - 8} textAnchor="middle" fontSize="11" className="fill-slate-500">{b}</text>
          </g>))}
        {pins.map((b) => {
          const i = r.buckets.indexOf(b.bucket); const band = [...ins, ...outs].find((z) => z.t === b.river_table);
          if (i < 0 || !band) return null;
          const yy = band.mid[i];
          return (<g key={b.break_id} className="cursor-pointer" onClick={() => nav(stepLink(b))}><title>{b.title}</title><circle cx={x(i)} cy={yy} r="7" fill="#fff" stroke="#D97706" strokeWidth="2" /><text x={x(i)} y={yy + 4} textAnchor="middle" fontSize="10" fill="#D97706">!</text></g>);
        })}
      </svg>
      {hover != null && (
        <div className="absolute top-2 bg-white border border-slate-200 rounded-lg shadow-lg p-3 text-[11px] w-60 pointer-events-none" style={{ left: `${Math.min(70, (x(hover) / W) * 100)}%` }}>
          <div className="font-semibold text-navy-900">{r.buckets[hover]}</div>
          <div className="text-[10px] text-slate-500 mb-1">{r.dates?.[r.buckets[hover]]?.label}</div>
          {r.dates?.[r.buckets[hover]]?.weekend && <div className="text-[10px] text-amber-700 bg-amber-50 rounded px-1.5 py-1 mb-1">A weekend - no contractual flows settle; weekend maturities roll to the next business day (Fed check PSV-01).</div>}
          {[...IN, ...OUT].map((t) => (<div key={t} className="flex"><span className="w-2.5 h-2.5 rounded-sm mr-1.5 mt-0.5" style={{ background: COLOR[t] }} />
            <span>{t} {r.tables[t]}</span><span className="ml-auto">{bn(r.values[r.buckets[hover]][t])}</span></div>))}
          <div className="flex border-t border-slate-100 mt-1 pt-1 font-semibold"><span>Net of the bucket</span><span className="ml-auto">{bn(up[hover] - dn[hover])}</span></div>
        </div>)}
    </div>
  );
}

// Today, the run: incomplete feeds (tables provisional), the river and the supplemental tables. The items themselves are decided on their step pages.
export default function TodayRun({ date }) {
  const [d, setD] = useState(null);
  useEffect(() => { setD(null); if (date) api.agToday(date).then(setD).catch(() => setD(false)); }, [date]);
  if (d === false) return null;
  if (!d) return <div className="text-xs text-slate-500">Loading the run...</div>;
  return (
    <div className="space-y-4">
      {d.feeds.incomplete.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 flex gap-2"><TriangleAlert className="w-4 h-4 mt-0.5 shrink-0" />
          <div><b>Partial run.</b> {d.feeds.incomplete.map((f) => `${f.feed}: ${f.details}`).join('; ')}.
            {d.feeds.provisional_tables.length > 0 && <> Provisional until the feed is complete: {d.feeds.provisional_tables.join(', ')}; the other tables ran.</>}</div></div>)}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-5 pt-3 text-[11px] text-slate-500 space-y-1">
          <div><span className="uppercase tracking-wider text-slate-400 mr-2">Above the line - inflows</span>{IN.map((t) => <span key={t} className="mr-3"><span className="inline-block w-2.5 h-2.5 rounded-sm mr-1 align-middle" style={{ background: COLOR[t] }} /><b>{t}</b> {d.river.tables[t]} {bn(d.river.totals[t])}</span>)}</div>
          <div><span className="uppercase tracking-wider text-slate-400 mr-2">Below the line - outflows</span>{OUT.map((t) => <span key={t} className="mr-3"><span className="inline-block w-2.5 h-2.5 rounded-sm mr-1 align-middle" style={{ background: COLOR[t] }} /><b>{t}</b> {d.river.tables[t]} {bn(d.river.totals[t])}</span>)}</div>
        </div>
        <div className="px-3"><River r={d.river} breaks={d.breaks} /></div>
        <div className="px-5 pb-1 text-[10px] text-slate-400">Every reported FR 2052a amount (unweighted, USD billions) by contractual maturity counted from the as-of date {d.date}: Open = no
          contractual maturity (demand deposits, open loans); Day 1 is the next calendar day; daily buckets grouped for display - {d.entity} - a ! marks an item waiting for you (click it to open it on its step page).
          The LCR module shows the weighted 30-day view.</div>
        <div className="px-5 py-3 border-t border-slate-100 text-xs flex flex-wrap gap-x-5 gap-y-1"><span className="uppercase tracking-wider text-[10px] text-slate-400 mt-0.5">Supplemental tables</span>
          {d.supplemental.map((s) => <span key={s.table_code} className={s.status === 'ok' ? 'text-slate-700' : 'text-amber-700 font-medium'}>
            {s.status === 'ok' ? <CircleCheck className="w-3.5 h-3.5 inline text-emerald-600 mr-1" /> : <TriangleAlert className="w-3.5 h-3.5 inline mr-1" />}
            <b>{s.table_code}</b> {s.name}{s.status !== 'ok' ? ` - ${s.status}` : ''}</span>)}</div>
      </div>
    </div>
  );
}
