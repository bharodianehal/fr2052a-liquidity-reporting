import React, { useState, useEffect } from 'react';
import { api } from '../api';
import AgentEvidence from './AgentEvidence';
import { Detail, AiFix, Actions, Btn, Decided } from './StepKit';
import { Check, PencilLine, Ban } from 'lucide-react';

// A comment the AI drafted for the Fed (S.C comment or variance commentary) - reviewed in Validate, with the exceptions, so the
// Comment file is final before the 6G files are generated.
export const TYPE = { COMMENT_DRAFT: ['S.C comment', 'comments'], VARIANCE_COMMENTARY: ['Variance commentary', 'commentary'] };
export const COMMENT_STATE = { PROPOSED: 'review', ACCEPTED: 'done', REJECTED: 'excluded' };
export const sug = (c) => (typeof c.suggestion === 'object' && c.suggestion ? c.suggestion : {});

// One comment for the Fed: the AI draft, the agent's evidence (incl. the rule agent's table-name check), then accept / edit / reject.
export default function CommentItem({ date, item, onDone }) {
  const [type, key] = TYPE[item.suggestion_type];
  const text = sug(item)[key] || '';
  const [mode, setMode] = useState(null);
  const [edit, setEdit] = useState(text);
  const [note, setNote] = useState('');
  const [msg, setMsg] = useState('');
  useEffect(() => { setMode(null); setEdit(text); setNote(''); setMsg(''); }, [item.suggestion_id, text]);
  const decide = async (decision, edits) => { setMsg(''); try { await api.wbAiDecide(item.suggestion_id, decision, note, edits); onDone(); } catch (e) { setMsg(e.message); } };
  return (
    <Detail tag={type} title={item.subject} s={item.s} sub={`${item.ai_function} | ${item.model || ''}`}>
      {item.s !== 'review' && <Decided>Decided{item.decided_by ? ` by ${item.decided_by}` : ''}{item.note ? `: ${item.note}` : ''}. Accepted comments go into the Comment file at the re-run of the validation.</Decided>}
      <AiFix confidence={item.confidence === 'None' ? null : item.confidence} title={text || 'No draft'} rationale={item.rationale} />
      {item.s === 'review' && (
        <Actions>
          <Btn primary icon={Check} onClick={() => decide('ACCEPTED')}>Accept AI draft</Btn>
          <Btn icon={PencilLine} active={mode === 'edit'} onClick={() => setMode(mode === 'edit' ? null : 'edit')}>Edit the draft</Btn>
          <Btn icon={Ban} active={mode === 'reject'} onClick={() => setMode(mode === 'reject' ? null : 'reject')}>Reject</Btn>
        </Actions>)}
      {mode === 'edit' && (
        <div className="space-y-2">
          <textarea value={edit} onChange={(e) => setEdit(e.target.value)} rows={5} className="w-full border border-slate-300 rounded px-2 py-1.5 text-xs" />
          <div className="flex gap-2"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" className="flex-1 border border-slate-200 rounded px-2 py-1.5 text-xs" />
            <button disabled={!edit.trim() || edit === text} onClick={() => decide('ACCEPTED', { [key]: edit })} className="px-4 py-1.5 rounded-lg text-xs font-medium bg-blue-600 text-white disabled:opacity-40">Save and accept</button></div>
        </div>)}
      {mode === 'reject' && (
        <div className="flex gap-2"><input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why the comment is not filed (required)" className="flex-1 border border-slate-200 rounded px-2 py-1.5 text-xs" />
          <button disabled={!note.trim()} onClick={() => decide('REJECTED')} className="px-4 py-1.5 rounded-lg text-xs font-medium bg-slate-700 text-white disabled:opacity-40">Reject</button></div>)}
      <AgentEvidence date={date} kind="ai" refKey={item.suggestion_id} onChange={onDone} />
      {msg && <div className="text-xs text-red-600">{msg}</div>}
    </Detail>
  );
}
