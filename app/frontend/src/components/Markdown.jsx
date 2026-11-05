import React from 'react';

// A small, safe markdown renderer for Genie answers: headings, paragraphs, bullet / numbered lists, tables, **bold**, `code`.
const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const inline = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code class="text-[12px] bg-slate-100 px-1 rounded">$1</code>');
const H = ({ html, cls }) => <div className={cls} dangerouslySetInnerHTML={{ __html: html }} />;

export default function Markdown({ text }) {
  const lines = String(text || '').split('\n');
  const out = [];
  for (let i = 0; i < lines.length;) {
    const l = lines[i];
    if (/^\s*\|/.test(l)) {   // table
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(lines[i]); i += 1; }
      const cells = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r)).map((r) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim()));
      out.push(
        <table key={i} className="text-xs my-2 border border-slate-200">
          <thead className="bg-slate-50"><tr>{cells[0].map((c, k) => <th key={k} className="text-left px-2 py-1" dangerouslySetInnerHTML={{ __html: inline(c) }} />)}</tr></thead>
          <tbody>{cells.slice(1).map((r, k) => <tr key={k} className="border-t border-slate-100">{r.map((c, j) => <td key={j} className="px-2 py-1" dangerouslySetInnerHTML={{ __html: inline(c) }} />)}</tr>)}</tbody>
        </table>);
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(l)) {   // list
      const items = [];
      const ordered = /^\s*\d+\./.test(l);
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, '')); i += 1; }
      const L = ordered ? 'ol' : 'ul';
      out.push(<L key={i} className={`${ordered ? 'list-decimal' : 'list-disc'} ml-5 my-1 space-y-0.5`}>{items.map((t, k) => <li key={k} dangerouslySetInnerHTML={{ __html: inline(t) }} />)}</L>);
      continue;
    }
    const h = l.match(/^(#{1,4})\s+(.*)/);
    if (h) out.push(<H key={i} cls="font-semibold text-navy-900 mt-2" html={inline(h[2])} />);
    else if (l.trim()) out.push(<H key={i} cls="my-1" html={inline(l)} />);
    i += 1;
  }
  return <div className="text-sm text-slate-800">{out}</div>;
}
