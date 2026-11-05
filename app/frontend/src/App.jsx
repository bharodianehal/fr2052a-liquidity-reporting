import React, { useState, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { api } from './api';
import Layout from './components/Layout';
import Today from './pages/Today';
import Collect from './pages/Collect';
import Validate from './pages/Validate';
import DataQualityStep from './pages/DataQualityStep';
import Enrich from './pages/Enrich';
import Release from './pages/Release';
import LCR from './pages/LCR';
import { BreakRedirect } from './components/AgentEvidence';
import Audit from './pages/Audit';
import Ask from './pages/Ask';
import Reference from './pages/Reference';
import History from './pages/History';
import Lineage from './pages/Lineage';
import SourceToReport from './pages/SourceToReport';

// The analyst's day: Today -> 1 Collect -> 2 Data quality -> 3 PID enrichment -> 4 Validate -> 5 Generate 6G & release.
// Ask, Reference and History support every step.
export default function App() {
  const [dates, setDates] = useState([]);
  const [selectedDate, setSelectedDate] = useState('');

  useEffect(() => {
    api.getDates().then((d) => {
      setDates(d);
      if (d.length > 0) setSelectedDate(d[0]);
    }).catch(() => {});
  }, []);

  return (
    <Layout dates={dates} selectedDate={selectedDate} onDateChange={setSelectedDate}>
      <Routes>
        <Route path="/" element={<Today date={selectedDate} />} />
        <Route path="/collect" element={<Collect date={selectedDate} />} />
        <Route path="/dq" element={<DataQualityStep date={selectedDate} />} />
        <Route path="/enrich" element={<Enrich date={selectedDate} />} />
        <Route path="/report" element={<Navigate to="/validate" replace />} />
        <Route path="/validate" element={<Validate date={selectedDate} />} />
        <Route path="/release" element={<Release date={selectedDate} />} />
        <Route path="/classify" element={<Navigate to="/enrich" replace />} />
        <Route path="/review" element={<Navigate to="/release" replace />} />
        <Route path="/submit" element={<Navigate to="/release" replace />} />
        <Route path="/genie" element={<Ask date={selectedDate} />} />
        <Route path="/reference" element={<Reference />} />
        <Route path="/dashboard" element={<SourceToReport />} />
        <Route path="/lineage" element={<Lineage date={selectedDate} />} />
        <Route path="/history" element={<History date={selectedDate} onDateChange={setSelectedDate} />} />
        <Route path="/lcr" element={<LCR date={selectedDate} />} />
        <Route path="/approvals" element={<Navigate to="/" replace />} />
        <Route path="/breaks/:id" element={<BreakRedirect />} />
        <Route path="/audit" element={<Audit date={selectedDate} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
