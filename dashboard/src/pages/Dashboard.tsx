import { FC, useState, useEffect } from 'react';
import { Card, CardContent } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Table } from '../components/ui/Table';
import { Button } from '../components/ui/Button';
import { Select } from '../components/ui/Select';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';

interface EquityCall {
  ticker: string;
  type: 'long_term' | 'swing' | 'sell';
  score: number;
  conviction: 'HIGH' | 'MEDIUM' | 'LOW';
  entry?: number;
  stop?: number;
  target?: number;
  thesis?: string;
  technical?: Record<string, unknown>;
  fundamental?: Record<string, unknown>;
  timestamp: string;
}

export const Dashboard: FC = () => {
  const [calls, setCalls] = useState<EquityCall[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState<'all' | 'long_term' | 'swing' | 'sell'>('all');
  const [lastUpdated, setLastUpdated] = useState<string>('');

  useEffect(() => {
    fetchCalls();
    // Poll for updates every 30 seconds
    const interval = setInterval(fetchCalls, 30000);
    return () => clearInterval(interval);
  }, []);

  const fetchCalls = async () => {
    try {
      const response = await fetch('/api/equity_calls');
      if (response.ok) {
        const data = await response.json();
        setCalls(data.calls || []);
        setLastUpdated(data.timestamp || new Date().toISOString());
      }
    } catch (error) {
      console.error('Failed to fetch calls:', error);
      // Fallback to local JSON
      const fallback = await fetch('/equity_calls.json');
      if (fallback.ok) {
        const data = await fallback.json();
        setCalls(data.calls || []);
      }
    } finally {
      setLoading(false);
    }
  };

  const filteredCalls = calls.filter(call => 
    filterType === 'all' || call.type === filterType
  );

  const columns = [
    { key: 'ticker', header: 'Ticker', render: (row: EquityCall) => (
      <div className="flex items-center gap-2">
        <span className="font-mono font-semibold">{row.ticker}</span>
        <Badge variant={row.type === 'long_term' ? 'success' : row.type === 'swing' ? 'info' : 'danger'} size="sm">
          {row.type.replace('_', ' ').toUpperCase()}
        </Badge>
      </div>
    )},
    { key: 'score', header: 'Score', render: (row: EquityCall) => (
      <div className="flex items-center gap-2">
        <span className={`font-mono font-bold ${row.score >= 80 ? 'text-accent-success' : row.score >= 60 ? 'text-accent-warning' : 'text-accent-danger'}`}>
          {row.score.toFixed(1)}
        </span>
        <div className="w-16 h-1.5 bg-bg-tertiary rounded-full overflow-hidden">
          <div className="h-full bg-accent-primary" style={{ width: `${row.score}%` }} />
        </div>
      </div>
    )},
    { key: 'conviction', header: 'Conviction', render: (row: EquityCall) => (
      <Badge variant={row.conviction === 'HIGH' ? 'success' : row.conviction === 'MEDIUM' ? 'warning' : 'neutral'} size="sm">
        {row.conviction}
      </Badge>
    )},
    { key: 'entry', header: 'Entry', render: (row: EquityCall) => row.entry ? `$${row.entry.toFixed(2)}` : '—' },
    { key: 'stop', header: 'Stop', render: (row: EquityCall) => row.stop ? `$${row.stop.toFixed(2)}` : '—' },
    { key: 'target', header: 'Target', render: (row: EquityCall) => row.target ? `$${row.target.toFixed(2)}` : '—' },
    { key: 'rr', header: 'R:R', render: (row: EquityCall) => {
      if (!row.entry || !row.stop || !row.target) return '—';
      const risk = row.entry - row.stop;
      const reward = row.target - row.entry;
      return risk > 0 ? `${(reward / risk).toFixed(1)}` : '—';
    }},
    { key: 'timestamp', header: 'Updated', render: (row: EquityCall) => (
      <span className="text-text-secondary">{new Date(row.timestamp).toLocaleString()}</span>
    )},
  ];

  return (
    <div className="space-y-6">
      {/* Header Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-text-secondary">Total Calls</p>
                <p className="text-2xl font-bold text-text-primary">{calls.length}</p>
              </div>
              <div className="w-12 h-12 rounded-xl bg-accent-primary/15 flex items-center justify-center text-2xl">📊</div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-text-secondary">Long-Term</p>
                <p className="text-2xl font-bold text-accent-success">
                  {calls.filter(c => c.type === 'long_term').length}
                </p>
              </div>
              <div className="w-12 h-12 rounded-xl bg-accent-success/15 flex items-center justify-center text-2xl">📈</div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-text-secondary">Swing Trades</p>
                <p className="text-2xl font-bold text-accent-info">
                  {calls.filter(c => c.type === 'swing').length}
                </p>
              </div>
              <div className="w-12 h-12 rounded-xl bg-accent-info/15 flex items-center justify-center text-2xl">⚡</div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-text-secondary">High Conviction</p>
                <p className="text-2xl font-bold text-accent-warning">
                  {calls.filter(c => c.conviction === 'HIGH').length}
                </p>
              </div>
              <div className="w-12 h-12 rounded-xl bg-accent-warning/15 flex items-center justify-center text-2xl">🎯</div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-text-secondary">Filter:</span>
              <Select
                value={filterType}
                onChange={(e) => setFilterType(e.target.value as "all" | "long_term" | "swing" | "sell")}
                options={[
                  { value: 'all', label: 'All Calls' },
                  { value: 'long_term', label: 'Long-Term' },
                  { value: 'swing', label: 'Swing' },
                  { value: 'sell', label: 'Sell' },
                ]}
                className="w-40"
              />
            </div>
            <div className="flex-1" />
            <div className="flex items-center gap-2 text-sm text-text-secondary">
              <span>Last updated:</span>
              <span className="font-mono">{lastUpdated ? new Date(lastUpdated).toLocaleString() : 'Never'}</span>
            </div>
            <Button variant="outline" size="sm" onClick={fetchCalls} disabled={loading}>
              {loading ? <LoadingSpinner size="sm" /> : '🔄 Refresh'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Calls Table */}
      <Card>
        <CardContent className="p-0">
          {loading && filteredCalls.length === 0 ? (
            <div className="flex items-center justify-center h-64">
              <LoadingSpinner size="lg" />
            </div>
          ) : (
            <Table
              data={filteredCalls}
              columns={columns}
              keyExtractor={(row) => row.ticker}
              striped
              hoverable
              onRowClick={(row) => window.open(`https://finance.yahoo.com/quote/${row.ticker}`, '_blank')}
              emptyMessage="No calls match the current filter"
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
};
