import React, { useState, useEffect } from 'react';
import { api } from '../api';
import { BookOpen } from 'lucide-react';

// PID dictionary: the FR 2052a is identified by product ID (PID) and field values - there are no MDRM codes in the 6G
// schema or the Instructions. MDRM codes appear only for the FR Y-15 Schedule G items computed from FR 2052a data.
export default function Metadata() {
  const [q, setQ] = useState('');
  const [data, setData] = useState({ products: [], stwf: [] });
  const [msg, setMsg] = useState('');

  useEffect(() => {
    const t = setTimeout(() => api.wbMetadata(q).then((d) => { setData(d); setMsg(''); }).catch((e) => setMsg(e.message)), 250);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-navy-900 flex items-center gap-2"><BookOpen className="w-5 h-5" /> PID dictionary</h1>
        <p className="text-sm text-slate-500 mt-1">
          Every FR 2052a value is identified by its product ID (PID) and its field values (counterparty, collateral class, maturity
          bucket, ...); the 6G schema and the Instructions use no MDRM codes. For each PID: its definition in the Instructions and the
          firm's derivation rules that assign it. MDRM codes appear only where the Fed defines them for 2052a-derived data - the
          FR Y-15 Schedule G short-term wholesale funding items.
        </p>
      </div>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search a PID or product name (e.g. O.D.1, brokered, I.A.3)"
        className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm" />
      {msg && <div className="text-xs text-red-600">{msg}</div>}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm max-h-[36rem] overflow-y-auto col-span-2">
          <div className="px-4 py-2 border-b border-slate-100 text-xs font-semibold text-navy-900 sticky top-0 bg-white">FR 2052a products ({data.products.length})</div>
          <table className="w-full text-xs">
            <thead className="text-slate-500"><tr><th className="text-left px-4 py-1">PID</th><th className="text-left">Product (6G name)</th>
              <th className="text-left">Table</th><th className="text-right">Instr. page</th><th className="text-right">PID rules</th>
              <th className="text-left pl-3 pr-4">Standard product types</th></tr></thead>
            <tbody>{data.products.map((p) => (
              <tr key={p.product_id} className="border-t border-slate-100 align-top">
                <td className="px-4 py-1.5 font-mono whitespace-nowrap">{p.product_id}</td>
                <td className="py-1.5">{p.product_name}{p.instructions_name && p.instructions_name !== p.product_name
                  ? <div className="text-[11px] text-slate-400">Instructions: {p.instructions_name}</div> : null}</td>
                <td>{p.table_name}</td><td className="text-right">{p.definition_page}</td>
                <td className="text-right">{p.pid_rules}</td><td className="pl-3 pr-4 text-slate-500">{p.standard_product_types || ''}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm max-h-[36rem] overflow-y-auto">
          <div className="px-4 py-2 border-b border-slate-100 text-xs font-semibold text-navy-900 sticky top-0 bg-white">
            FR Y-15 Schedule G MDRM, from FR 2052a PIDs ({data.stwf.length})</div>
          <table className="w-full text-xs">
            <tbody>{data.stwf.map((s) => (
              <tr key={`${s.stwf_item}-${s.maturity_column}`} className="border-t border-slate-100 align-top">
                <td className="px-4 py-1">{s.stwf_item} {s.maturity_column}</td><td className="font-mono">{s.mdrm}</td>
                <td className="pr-4">{s.description}{s.product_ids ? <div className="text-[11px] text-slate-400 font-mono">{s.product_ids}</div> : null}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
