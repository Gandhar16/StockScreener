import { FC } from 'react';
import { Routes, Route } from 'react-router-dom';
import { Layout } from '@/components/Layout';
import { Dashboard } from '@/pages/Dashboard';
import { Calls } from '@/pages/Calls';
import { Scanner } from '@/pages/Scanner';
import { Backtest } from '@/pages/Backtest';
import { Settings } from '@/pages/Settings';

export const App: FC = () => {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/calls" element={<Calls />} />
        <Route path="/scanner" element={<Scanner />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
};

// Need to import Navigate
import { Navigate } from 'react-router-dom';
