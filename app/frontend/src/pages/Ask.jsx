import React, { useState, useEffect } from 'react';
import GeniePage from './GeniePage';

// Genie: the app's one place for questions - the FR 2052a Genie Agent, embedded.
export default function Ask({ date }) {
  const [ws, setWs] = useState({});
  useEffect(() => { fetch('/api/workspace-url').then((r) => r.json()).then(setWs).catch(() => {}); }, []);
  return <GeniePage date={date} embedUrl={ws.genie_embed_url} genieUrl={ws.genie_url} />;
}
