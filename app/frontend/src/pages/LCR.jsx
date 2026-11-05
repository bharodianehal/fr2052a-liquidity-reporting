import React, { useState, useEffect, useMemo } from 'react';
import { api } from '../api';
import DashboardEmbed from '../components/DashboardEmbed';
import { ArrowRight, ChevronLeft, ChevronRight, Search, X, Sparkles, Check, Download, PencilLine, RotateCcw } from 'lucide-react';

const ENTITIES = [['ENT001', 'Consolidated BHC'], ['ENT002', 'Bank (solo)']];
const TABS = [['dashboard', 'Dashboard'], ['disclosure', 'Disclosure'], ['calculation', 'Calculation'], ['mapping', 'Data mapping'], ['reference', 'Regulatory reference']];
const num = (v, d = 1) => (v == null || v === '' ? '' : parseFloat(v).toLocaleString('en-US', { maximumFractionDigits: d, minimumFractionDigits: d }));
const pct = (v, d = 1) => (v == null || v === '' ? '' : `${(parseFloat(v) * 100).toFixed(d)}%`);
const DIR = { OUTFLOW: 'text-red-700', INFLOW: 'text-emerald-700', HQLA: 'text-blue-700' };
const Th = ({ children, right }) => <th className={`px-3 py-1.5 font-medium ${right ? 'text-right' : 'text-left'}`}>{children}</th>;

function Card({ title, sub, children }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
      <div className="px-4 py-2.5 border-b border-slate-100"><div className="text-sm font-semibold text-navy-900">{title}</div>
        {sub && <div className="text-[11px] text-slate-500">{sub}</div>}</div>
      {children}
    </div>
  );
}

// The regulation as the engine applies it: the 12 CFR 249 parameters, the HQLA classes of collateral, and the FR 2052a Appendix VI rules.
function Reference() {
  const [r, setR] = useState(null);
  const [q, setQ] = useState('');
  const [dir, setDir] = useState('');
  useEffect(() => { api.wbLcrReference().then(setR).catch(() => {}); }, []);
  const rules = useMemo(() => (r?.rules || []).filter((x) => (!dir || x.flow_direction === dir) && (!q || JSON.stringify(x).toLowerCase().includes(q.toLowerCase()))), [r, q, dir]);
  if (!r) return <div className="text-sm text-slate-500">Loading...</div>;
  const cond = (x) => [x.sub_product_condition && `sub-product ${x.sub_product_condition}`, x.counterparty_condition && `counterparty ${x.counterparty_condition}`,
    x.counterparty_category_condition && `category ${x.counterparty_category_condition}`, x.collateral_hqla_condition && `collateral ${x.collateral_hqla_condition}`,
    x.insured_condition && `insured ${x.insured_condition}`, x.maturity_condition && x.maturity_condition !== 'ANY' && `maturity ${x.maturity_condition} days`,
    x.other_condition].filter(Boolean).join('; ');
  return (
    <div className="space-y-4">
      <Card title="Parameters of the calculation" sub="12 CFR 249 (Regulation WW) - the constants the LCR engine applies">
        <table className="w-full text-xs"><thead className="bg-slate-50 text-slate-500"><tr><Th>Parameter</Th><Th>Value</Th><Th>Regulation</Th><Th>How it is applied</Th></tr></thead>
          <tbody>{r.parameters.map((p) => (
            <tr key={p.parameter} className="border-t border-slate-100"><td className="px-3 py-1.5 font-medium">{p.parameter}</td><td className="px-3">{p.value}</td>
              <td className="px-3 font-mono text-[11px]">{p.cite}</td><td className="px-3 text-slate-600">{p.how}</td></tr>))}</tbody></table>
      </Card>
      <Card title={`LCR rules - FR 2052a Appendix VI (${r.rules.length})`} sub="Each rule maps FR 2052a products (PIDs) and conditions to an LCR category and its rate; when several match, the lowest priority applies">
        <div className="px-4 py-2 flex gap-2 items-center border-b border-slate-100">
          {['', 'HQLA', 'OUTFLOW', 'INFLOW'].map((d) => <button key={d} onClick={() => setDir(d)} className={`px-2.5 py-1 rounded text-xs border ${dir === d ? 'bg-navy-900 text-white border-navy-900' : 'border-slate-200'}`}>{d || 'All'}</button>)}
          <div className="ml-auto flex items-center gap-1 border border-slate-200 rounded px-2"><Search className="w-3.5 h-3.5 text-slate-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="rule, PID, section..." className="text-xs py-1 outline-none w-44" /></div>
        </div>
        <div className="overflow-auto max-h-[32rem]"><table className="w-full text-xs"><thead className="bg-slate-50 text-slate-500 sticky top-0"><tr>
          <Th>Rule</Th><Th>Section</Th><Th>Flow</Th><Th>Name</Th><Th>FR 2052a PIDs</Th><Th>Conditions</Th><Th right>Rate</Th><Th>Disclosure line</Th></tr></thead>
          <tbody>{rules.map((x) => (
            <tr key={x.rule_id} className="border-t border-slate-100 align-top"><td className="px-3 py-1.5 font-mono">{x.rule_id}</td><td className="px-3 whitespace-nowrap">{x.rule_section}</td>
              <td className={`px-3 font-medium ${DIR[x.flow_direction] || ''}`}>{x.flow_direction}</td>
              <td className="px-3">{x.rule_name}<div className="text-[10px] text-slate-400">{x.rule_description}</div></td>
              <td className="px-3 font-mono text-[11px] max-w-[12rem] break-words">{x.applicable_product_ids}</td><td className="px-3 text-slate-600 text-[11px]">{cond(x)}</td>
              <td className="px-3 text-right font-semibold">{pct(x.rate, 0)}</td><td className="px-3 text-[11px] text-slate-600">{x.disclosure_line}</td></tr>))}</tbody></table></div>
      </Card>
      <Card title="HQLA classes of collateral" sub="Which collateral counts as HQLA, at which level and with which haircut">
        <div className="overflow-auto max-h-80"><table className="w-full text-xs"><thead className="bg-slate-50 text-slate-500 sticky top-0"><tr><Th>Collateral class</Th><Th>Description</Th><Th>Group</Th><Th>HQLA level</Th><Th right>Haircut</Th></tr></thead>
          <tbody>{r.hqla_classes.map((c) => (
            <tr key={c.collateral_class} className="border-t border-slate-100"><td className="px-3 py-1 font-mono">{c.collateral_class}</td><td className="px-3">{c.description}</td>
              <td className="px-3 text-slate-500">{c.category_group}</td><td className="px-3">{c.is_hqla === 'true' || c.is_hqla === true ? c.hqla_level : 'Not HQLA'}</td>
              <td className="px-3 text-right">{c.lcr_haircut_pct != null ? pct(c.lcr_haircut_pct, 0) : ''}</td></tr>))}</tbody></table></div>
      </Card>
    </div>
  );
}

// How today's source data reaches each LCR rule: source feed -> bank product code -> standard product type -> PID -> LCR rule -> rate.
function Mapping({ date, entity }) {
  const [rows, setRows] = useState(null);
  const [unused, setUnused] = useState(false);
  const [dir, setDir] = useState('');
  useEffect(() => { setRows(null); if (date) api.wbLcrMapping(date, entity).then(setRows).catch(() => setRows([])); }, [date, entity]);
  const shown = (rows || []).filter((x) => (unused || parseInt(x.positions) > 0) && (!dir || x.flow_direction === dir));
  const notUsed = (rows || []).filter((x) => parseInt(x.positions) === 0).length;
  const chain = ['Source feed', 'Bank product code', 'Standard product type', 'FR 2052a PID', 'LCR rule (Appendix VI)', 'Rate x amount'];
  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-3 flex flex-wrap items-center gap-2 text-xs">
        {chain.map((c, i) => <React.Fragment key={c}><span className="px-2.5 py-1 rounded-lg bg-slate-100 text-navy-900 font-medium">{c}</span>{i < chain.length - 1 && <ArrowRight className="w-3.5 h-3.5 text-slate-400" />}</React.Fragment>)}
        <span className="text-slate-500 ml-2">the bank's codes are mapped to standard product types, the PID rules assign the FR 2052a product, the Appendix VI rules the LCR category</span>
      </div>
      <Card title={`Source data per LCR rule - ${date}, ${entity}`} sub={rows ? `${rows.length - notUsed} rules applied today, ${notUsed} not used today` : 'Loading...'}>
        <div className="px-4 py-2 flex gap-2 items-center border-b border-slate-100">
          {['', 'HQLA', 'OUTFLOW', 'INFLOW'].map((d) => <button key={d} onClick={() => setDir(d)} className={`px-2.5 py-1 rounded text-xs border ${dir === d ? 'bg-navy-900 text-white border-navy-900' : 'border-slate-200'}`}>{d || 'All'}</button>)}
          <label className="ml-auto text-xs flex items-center gap-1"><input type="checkbox" checked={unused} onChange={(e) => setUnused(e.target.checked)} />show rules not used today</label>
        </div>
        <div className="overflow-auto max-h-[40rem]"><table className="w-full text-xs"><thead className="bg-slate-50 text-slate-500 sticky top-0"><tr>
          <Th>LCR rule</Th><Th>Flow</Th><Th>Source feeds</Th><Th>Source systems</Th><Th>Bank product codes</Th><Th>Standard product types</Th><Th>PIDs</Th>
          <Th right>Positions</Th><Th right>Amount (USD mm)</Th><Th right>Rate</Th><Th right>Weighted (USD mm)</Th></tr></thead>
          <tbody>{shown.map((x) => (
            <tr key={x.rule_id} className={`border-t border-slate-100 align-top ${parseInt(x.positions) ? '' : 'text-slate-400'}`}>
              <td className="px-3 py-1.5"><span className="font-mono">{x.rule_id}</span> <span className="text-slate-400">{x.rule_section}</span><div>{x.rule_name}</div></td>
              <td className={`px-3 font-medium ${DIR[x.flow_direction] || ''}`}>{x.flow_direction}</td>
              <td className="px-3">{x.source_feeds}</td><td className="px-3">{x.source_systems}</td><td className="px-3 font-mono text-[11px] max-w-[14rem] break-words">{x.bank_product_codes}</td>
              <td className="px-3 text-[11px]">{x.standard_product_types}</td><td className="px-3 font-mono text-[11px]">{x.pids_matched || <span className="text-slate-400">{x.applicable_product_ids}</span>}</td>
              <td className="px-3 text-right">{x.positions}</td><td className="px-3 text-right">{num(x.amount_usd)}</td><td className="px-3 text-right">{pct(x.rate, 0)}</td>
              <td className="px-3 text-right font-semibold">{num(x.weighted_usd)}</td></tr>))}</tbody></table></div>
      </Card>
    </div>
  );
}

// The LCR of the day step by step, each rule's contribution, and the positions behind a rule.
function Calculation({ date, entity }) {
  const [c, setC] = useState(null);
  const [err, setErr] = useState('');
  const [rule, setRule] = useState(null);
  const [page, setPage] = useState(0);
  const [pos, setPos] = useState(null);
  useEffect(() => { setC(null); setRule(null); setErr(''); if (date) api.wbLcrCalculation(date, entity).then(setC).catch((e) => setErr(e.message)); }, [date, entity]);
  useEffect(() => { setPos(null); if (rule) api.wbLcrRulePositions(date, rule.rule_id, entity, page).then(setPos).catch(() => {}); }, [date, entity, rule, page]);
  if (err) return <div className="text-sm text-red-600">{err}</div>;
  if (!c) return <div className="text-sm text-slate-500">Loading...</div>;
  const groups = [...new Set(c.steps.map((s) => s.group))];
  return (
    <div className="grid grid-cols-5 gap-4">
      <div className="col-span-2">
        <Card title={`LCR ${pct(c.lcr_ratio)} - ${c.compliant === 'true' || c.compliant === true ? 'compliant (minimum 100%)' : 'BELOW 100%'}`}
          sub={`${date}, ${entity} - USD mm${parseInt(c.unmatched_positions) ? `; ${c.unmatched_positions} positions matched no rule` : '; every position matched a rule'}`}>
          <table className="w-full text-xs"><tbody>{groups.map((g) => (
            <React.Fragment key={g}>
              <tr className="bg-slate-50"><td colSpan={3} className="px-3 py-1 text-[10px] uppercase tracking-wider text-slate-500">{g}</td></tr>
              {c.steps.filter((s) => s.group === g).map((s) => (
                <tr key={s.step} className={`border-t border-slate-100 ${s.total ? 'font-semibold text-navy-900' : ''}`}>
                  <td className="px-3 py-1.5">{s.step}<div className="text-[10px] font-normal text-slate-400">{s.how}</div></td>
                  <td className="px-3 text-right whitespace-nowrap align-top pt-1.5">{s.usd != null ? num(s.usd) : pct(s.pct)}</td></tr>))}
            </React.Fragment>))}</tbody></table>
        </Card>
      </div>
      <div className="col-span-3 space-y-4">
        <Card title="Contribution of each LCR rule" sub="Pick a rule to see the positions it applied to">
          <div className="overflow-auto max-h-[28rem]"><table className="w-full text-xs"><thead className="bg-slate-50 text-slate-500 sticky top-0"><tr>
            <Th>Flow</Th><Th>Rule</Th><Th>Name</Th><Th right>Positions</Th><Th right>Amount</Th><Th right>Rate</Th><Th right>Weighted</Th></tr></thead>
            <tbody>{c.by_rule.map((x) => (
              <tr key={x.rule_id} onClick={() => { setRule(x); setPage(0); }} className={`border-t border-slate-100 cursor-pointer ${rule?.rule_id === x.rule_id ? 'bg-blue-50' : 'hover:bg-slate-50'}`}>
                <td className={`px-3 py-1 font-medium ${DIR[x.flow_direction] || ''}`}>{x.flow_direction}</td><td className="px-3 font-mono">{x.rule_id}<span className="text-slate-400 ml-1">{x.rule_section}</span></td>
                <td className="px-3">{x.rule_name}</td><td className="px-3 text-right">{x.positions}</td><td className="px-3 text-right">{num(x.amount_usd)}</td>
                <td className="px-3 text-right">{pct(x.rate, 0)}</td><td className="px-3 text-right font-semibold">{num(x.weighted_usd)}</td></tr>))}</tbody></table></div>
        </Card>
        {rule && (
          <Card title={`${rule.rule_id} ${rule.rule_name} - positions`} sub={pos ? `${page * pos.size + 1}-${Math.min((page + 1) * pos.size, pos.total)} of ${pos.total}` : 'Loading...'}>
            <div className="px-4 py-1.5 flex justify-end gap-1 border-b border-slate-100">
              <button disabled={page === 0} onClick={() => setPage(page - 1)} className="p-1 rounded border border-slate-200 disabled:opacity-30"><ChevronLeft className="w-3.5 h-3.5" /></button>
              <button disabled={!pos || (page + 1) * pos.size >= pos.total} onClick={() => setPage(page + 1)} className="p-1 rounded border border-slate-200 disabled:opacity-30"><ChevronRight className="w-3.5 h-3.5" /></button>
              <button onClick={() => setRule(null)} className="p-1"><X className="w-3.5 h-3.5 text-slate-400" /></button></div>
            <div className="overflow-auto max-h-96"><table className="w-full text-[11px]"><thead className="bg-slate-50 text-slate-500 sticky top-0"><tr>
              <Th>Position</Th><Th>System</Th><Th>Bank code</Th><Th>PID</Th><Th>Counterparty</Th><Th>Collateral</Th><Th>Bucket</Th><Th right>Amount</Th><Th right>Rate</Th><Th right>Weighted</Th></tr></thead>
              <tbody>{(pos?.rows || []).map((p) => (
                <tr key={p.position_id} className="border-t border-slate-100"><td className="px-3 py-1 font-mono">
                  <a href={`/lineage?position=${encodeURIComponent(p.position_id)}`} className="text-blue-700 hover:underline">{p.position_id}</a></td>
                  <td className="px-3">{p.source_system}</td><td className="px-3 font-mono">{p.source_product_code}</td><td className="px-3 font-mono">{p.product_id}</td>
                  <td className="px-3">{p.counterparty}</td><td className="px-3">{p.collateral_class}{p.hqla_level ? ` (${p.hqla_level})` : ''}</td><td className="px-3">{p.maturity_bucket}</td>
                  <td className="px-3 text-right">{num(p.amount_usd)}</td><td className="px-3 text-right">{pct(p.rate, 0)}</td><td className="px-3 text-right">{num(p.weighted_amount_usd)}</td></tr>))}</tbody></table></div>
          </Card>
        )}
      </div>
    </div>
  );
}


// AI first: why the LCR moved since the prior day - the exact attribution, explained by ai_query from those numbers only.
function WhyItMoved({ date, entity }) {
  const [x, setX] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => { setX(null); setErr(''); if (date) api.wbLcrExplain(date, entity).then(setX).catch((e) => setErr(e.message)); }, [date, entity]);
  if (err) return <div className="text-xs text-slate-500">{err}</div>;
  const pp = (v) => `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)} pp`;
  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-blue-900"><Sparkles className="w-4 h-4" />Why the LCR moved{x ? ` - ${x.prior_date} to ${x.date}` : ''}</div>
      {!x && <div className="text-xs text-blue-800 mt-1 animate-pulse">Attributing the change...</div>}
      {x && <>
        <div className="text-sm font-semibold text-navy-900 mt-1">{x.headline}</div>
        <div className="text-xs text-slate-700 mt-1">{x.explanation}</div>
        <table className="w-full text-xs mt-3 bg-white rounded"><thead className="text-slate-500"><tr><Th>Driver</Th><Th right>Prior (USD mm)</Th><Th right>Today</Th><Th right>Change</Th><Th right>Effect on the LCR</Th></tr></thead>
          <tbody>{x.attribution.filter((a) => Math.abs(a.change) > 0.05).sort((a, b) => Math.abs(b.lcr_effect) - Math.abs(a.lcr_effect)).map((a) => (
            <tr key={a.driver} className="border-t border-slate-100"><td className="px-3 py-1">{a.driver}</td><td className="px-3 text-right">{num(a.prior)}</td><td className="px-3 text-right">{num(a.today)}</td>
              <td className="px-3 text-right">{num(a.change)}</td><td className={`px-3 text-right font-semibold ${a.lcr_effect >= 0 ? 'text-emerald-700' : 'text-red-700'}`}>{pp(a.lcr_effect)}</td></tr>))}
            <tr className="border-t border-slate-200 font-semibold"><td className="px-3 py-1">LCR</td><td className="px-3 text-right">{pct(x.lcr_prior, 2)}</td><td className="px-3 text-right">{pct(x.lcr_today, 2)}</td>
              <td /><td className="px-3 text-right">{pp(x.lcr_today - x.lcr_prior)}</td></tr></tbody></table>
        <div className="text-[10px] text-slate-400 mt-1">{x.generated_by}; the effects add up to the LCR change exactly.</div>
      </>}
    </div>
  );
}

// The quarterly public disclosure (12 CFR 249.90-91): the 35-line template over a period, and the AI-drafted qualitative sections
// in the structure large US banks publish - reviewed, edited and approved by the analyst, then exported.
function Disclosure({ entity }) {
  const [dates, setDates] = useState([]);
  const [range, setRange] = useState(null);
  const [d, setD] = useState(null);
  const [draft, setDraft] = useState([]);
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState({});
  const [open, setOpen] = useState(null);
  const [msg, setMsg] = useState('');
  useEffect(() => { api.getDates().then((x) => { setDates(x); setRange([x[x.length - 1], x[0]]); }).catch(() => {}); }, []);
  const load = () => { if (!range) return; setD(null); api.wbLcrDisclosure(range[0], range[1], entity).then(setD).catch((e) => setMsg(e.message));
    api.wbLcrDraft(range[0], range[1], entity).then(setDraft).catch(() => setDraft([])); };
  useEffect(load, [range, entity]);
  const generate = async () => { setBusy(true); setMsg(''); try { await api.wbLcrDraftGenerate(range[0], range[1], entity); load(); } catch (e) { setMsg(e.message); } setBusy(false); };
  const act = async (s, action) => { setMsg(''); try { await api.wbLcrSection({ draft_id: s.draft_id, section: s.section, action, text: edit[s.section] ?? s.final_text });
    setEdit((x) => { const n = { ...x }; delete n[s.section]; return n; }); load(); } catch (e) { setMsg(e.message); } };
  const fmt = (v, ln) => (v == null ? '' : ln === 33 || ln === 35 ? pct(v, 0) : parseFloat(v).toLocaleString('en-US', { maximumFractionDigits: 0 }));
  const LABELS = { lcr_variance: 'LCR variance', drivers: 'Drivers of the average LCR', hqla_composition: 'HQLA composition', outflow_drivers: 'Outflow drivers',
    inflow_drivers: 'Inflow drivers', funding_concentration: 'Concentration of funding sources', derivatives_collateral: 'Derivative exposures and collateral calls',
    currency_mismatch: 'Currency mismatch', liquidity_management: 'Centralized liquidity management' };
  const approved = draft.filter((s) => s.status === 'APPROVED').length;
  if (!range) return <div className="text-sm text-slate-500">Loading...</div>;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-slate-500">Period:</span>
        <select value={range[0]} onChange={(e) => setRange([e.target.value, range[1]])} className="border border-slate-200 rounded px-2 py-1">{[...dates].reverse().map((x) => <option key={x}>{x}</option>)}</select>
        <span>to</span>
        <select value={range[1]} onChange={(e) => setRange([range[0], e.target.value])} className="border border-slate-200 rounded px-2 py-1">{dates.map((x) => <option key={x}>{x}</option>)}</select>
        <span className="text-slate-500">{d ? `${d.days} daily observations - the quarter-to-date in this demo` : ''}</span>
        <a href={api.wbLcrExportUrl(range[0], range[1], entity)} className="ml-auto flex items-center gap-1 text-blue-700 hover:underline"><Download className="w-3.5 h-3.5" />Export the disclosure</a>
      </div>
      {msg && <div className="text-xs text-red-600">{msg}</div>}
      <div className="grid grid-cols-2 gap-4">
        <Card title="Quantitative disclosure (12 CFR 249.91)" sub={`Average of the daily amounts, USD mm - ${entity}${d ? `, ${d.start} to ${d.end}` : ''}`}>
          {!d ? <div className="p-4 text-xs text-slate-500">Loading...</div> : <>
            <table className="w-full text-[11px]"><thead className="bg-slate-50 text-slate-500"><tr><Th /><Th /><Th right>Unweighted</Th><Th right>Weighted</Th></tr></thead>
              <tbody>{d.lines.map((x, i) => (
                <React.Fragment key={x.line}>
                  {(i === 0 || d.lines[i - 1].section !== x.section) && <tr className="bg-slate-50"><td colSpan={4} className="px-3 py-1 text-[10px] uppercase tracking-wider text-slate-500">{x.section}</td></tr>}
                  <tr onClick={() => setOpen(open === x.line ? null : x.line)} className={`border-t border-slate-100 ${x.rules.length ? 'cursor-pointer hover:bg-slate-50' : ''} ${[1, 19, 28, 35].includes(x.line) ? 'font-semibold' : ''}`}>
                    <td className="px-3 py-1 text-slate-400 w-6">{x.line}</td><td className="py-1" style={{ paddingLeft: 4 + x.indent * 14 }}>{x.text}
                      {open === x.line && x.rules.length > 0 && <div className="text-[10px] text-blue-700 font-mono">{x.rules.join(', ')}</div>}</td>
                    <td className="px-3 text-right">{fmt(x.unweighted, x.line)}</td><td className="px-3 text-right">{fmt(x.weighted, x.line)}</td></tr>
                </React.Fragment>))}</tbody></table>
            <div className="px-3 py-2 text-[10px] text-slate-400">{d.note} Click a line to see the LCR rules in it.</div></>}
        </Card>
        <Card title="Qualitative disclosure - AI draft for review" sub={draft.length ? `${approved} of ${draft.length} sections approved; drafted by ${draft[0].model} from this period's numbers only` : 'Not drafted yet'}>
          <div className="p-3 space-y-3">
            <button disabled={busy} onClick={generate} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white disabled:opacity-40">
              <Sparkles className="w-3.5 h-3.5" />{busy ? 'Drafting...' : draft.length ? 'Redraft with AI' : 'Draft with AI'}</button>
            {draft.map((s) => (
              <div key={s.section} className={`rounded-lg border p-3 ${s.status === 'APPROVED' ? 'border-emerald-200 bg-emerald-50/40' : 'border-slate-200'}`}>
                <div className="flex items-center gap-2"><span className="text-xs font-semibold text-navy-900">{LABELS[s.section] || s.section}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border ${s.status === 'APPROVED' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : s.status === 'EDITED' ? 'bg-blue-50 text-blue-700 border-blue-200' : 'bg-amber-50 text-amber-700 border-amber-200'}`}>
                    {s.status === 'APPROVED' ? `Approved by ${s.approved_by}` : s.status === 'EDITED' ? `Edited by ${s.edited_by}` : 'AI draft'}</span>
                  <span className="ml-auto flex gap-1">
                    {s.status !== 'APPROVED' && edit[s.section] === undefined && <button onClick={() => setEdit({ ...edit, [s.section]: s.final_text })} className="p-1 rounded border border-slate-200" title="Edit"><PencilLine className="w-3.5 h-3.5" /></button>}
                    {s.status !== 'APPROVED' && <button onClick={() => act(s, edit[s.section] !== undefined ? 'save' : 'approve')} className="flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-600 text-white text-[11px]">
                      <Check className="w-3 h-3" />{edit[s.section] !== undefined ? 'Save' : 'Approve'}</button>}
                    {s.status === 'APPROVED' && <button onClick={() => act(s, 'reopen')} className="p-1 rounded border border-slate-200" title="Re-open"><RotateCcw className="w-3.5 h-3.5" /></button>}
                  </span></div>
                {edit[s.section] !== undefined
                  ? <textarea value={edit[s.section]} onChange={(e) => setEdit({ ...edit, [s.section]: e.target.value })} rows={5} className="w-full mt-2 border border-slate-200 rounded p-2 text-xs" />
                  : <p className="text-xs text-slate-700 mt-1 whitespace-pre-wrap">{s.final_text}</p>}
              </div>))}
          </div>
        </Card>
      </div>
    </div>
  );
}

// LCR module: the dashboard, the regulatory reference, how the source data maps to it, and the calculation step by step.
export default function LCR({ date }) {
  const [tab, setTab] = useState('dashboard');
  const [entity, setEntity] = useState('ENT001');
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-navy-900">Liquidity Coverage Ratio</h1>
        <p className="text-sm text-slate-500 mt-1">12 CFR 249 (Regulation WW), computed from the FR 2052a positions with the Appendix VI mapping - and reported as S.L.6.
          HQLA after haircuts and caps, against the net cash outflows of the next 30 days; minimum 100%.</p>
      </div>
      <div className="flex items-center gap-1 border-b border-slate-200">
        {TABS.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === k ? 'border-blue-600 text-navy-900' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>{label}</button>))}
        {tab !== 'reference' && (
          <div className="ml-auto flex gap-1 pb-1">{ENTITIES.map(([e, l]) => (
            <button key={e} onClick={() => setEntity(e)} className={`px-3 py-1 rounded-lg text-xs border ${entity === e ? 'bg-navy-900 text-white border-navy-900' : 'bg-white border-slate-200'}`}>{e} {l}</button>))}</div>)}
      </div>
      {tab === 'dashboard' && <div className="space-y-4"><WhyItMoved date={date} entity={entity} /><DashboardEmbed dashboard="lcr" page="lcr" title="LCR" height={1250} /></div>}
      {tab === 'disclosure' && <Disclosure entity={entity} />}
      {tab === 'reference' && <Reference />}
      {tab === 'mapping' && <Mapping date={date} entity={entity} />}
      {tab === 'calculation' && <Calculation date={date} entity={entity} />}
    </div>
  );
}
