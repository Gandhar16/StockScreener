import { FC, useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
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
  risks?: string[];
  technical?: Record<string, unknown>;
  fundamental?: Record<string, unknown>;
  entry_signal?: string;
  timestamp: string;
}

export const Calls: FC = () => {
  const [calls, setCalls] = useState<EquityCall[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedCall, setSelectedCall] = useState<EquityCall | null>(null);
  const [filterType, setFilterType] = useState<'all' | 'long_term' | 'swing' | 'sell'>('all');
  const [sortBy, setSortBy] = useState<'score' | 'ticker' | 'timestamp'>('score');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  useEffect(() => {
    fetchCalls();
  }, []);

  const fetchCalls = async () => {
    try {
      const response = await fetch('/api/equity_calls');
      if (response.ok) {
        const data = await response.json();
        setCalls(data.calls || []);
      }
    } catch {
      const fallback = await fetch('/equity_calls.json');
      if (fallback.ok) {
        const data = await fallback.json();
        setCalls(data.calls || []);
      }
    } finally {
      setLoading(false);
    }
  };

  const filteredCalls = calls
    .filter(call => filterType === 'all' || call.type === filterType)
    .sort((a, b) => {
      const aVal = a[sortBy as keyof EquityCall];
      const bVal = b[sortBy as keyof EquityCall];
      const order = sortOrder === 'asc' ? 1 : -1;
      if (typeof aVal === 'number' && typeof bVal === 'number') return (aVal - bVal) * order;
      return String(aVal).localeCompare(String(bVal)) * order;
    });


  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Equity Calls</h1>
          <p className="text-text-secondary">All generated equity calls with detailed analysis</p>
        </div>
        <div className="flex items-center gap-3">
          <Select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value as "all" | "long_term" | "swing" | "sell")}
            options={[
              { value: 'all', label: 'All Types' },
              { value: 'long_term', label: 'Long-Term' },
              { value: 'swing', label: 'Swing' },
              { value: 'sell', label: 'Sell' },
            ]}
            className="w-40"
          />
          <Select
            value={sortBy}
            onChange={(e) => { setSortBy(e.target.value as "score" | "ticker" | "timestamp"); setSortOrder('desc'); }}
            options={[
              { value: 'score', label: 'Sort by Score' },
              { value: 'ticker', label: 'Sort by Ticker' },
              { value: 'timestamp', label: 'Sort by Date' },
            ]}
            className="w-40"
          />
          <Button variant="outline" size="sm" onClick={fetchCalls} disabled={loading}>
            {loading ? <LoadingSpinner size="sm" /> : '🔄 Refresh'}
          </Button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-text-secondary">Total Calls</p>
            <p className="text-2xl font-bold text-text-primary">{calls.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-text-secondary">Long-Term</p>
            <p className="text-2xl font-bold text-accent-success">{calls.filter(c => c.type === 'long_term').length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-text-secondary">Swing Trades</p>
            <p className="text-2xl font-bold text-accent-info">{calls.filter(c => c.type === 'swing').length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-text-secondary">High Conviction</p>
            <p className="text-2xl font-bold text-accent-warning">{calls.filter(c => c.conviction === 'HIGH').length}</p>
          </CardContent>
        </Card>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-64">
              <LoadingSpinner size="lg" />
            </div>
          ) : (
            <Table
              data={filteredCalls}
              columns={[
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
                { key: 'conviction', header: 'Conviction', render: (row: EquityCall) => (
                  <Badge variant={row.conviction === 'HIGH' ? 'success' : row.conviction === 'MEDIUM' ? 'warning' : 'neutral'} size="sm">
                    {row.conviction}
                  </Badge>
                )},
                { key: 'timestamp', header: 'Updated', render: (row: EquityCall) => (
                  <span className="text-text-secondary">{new Date(row.timestamp).toLocaleString()}</span>
                )},
              ]}
              keyExtractor={(row) => row.ticker}
              striped
              hoverable
              onRowClick={(row) => setSelectedCall(row)}
              emptyMessage="No calls available"
            />
          )}
        </CardContent>
      </Card>

      {/* Detail Modal */}
      {selectedCall && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-card rounded-2xl border border-border-color max-w-3xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div className="p-6 border-b border-border-color flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="font-mono text-2xl font-bold">{selectedCall.ticker}</span>
                <Badge variant={selectedCall.type === 'long_term' ? 'success' : selectedCall.type === 'swing' ? 'info' : 'danger'} size="lg">
                  {selectedCall.type.replace('_', ' ').toUpperCase()}
                </Badge>
                <Badge variant={selectedCall.conviction === 'HIGH' ? 'success' : selectedCall.conviction === 'MEDIUM' ? 'warning' : 'neutral'} size="lg">
                  {selectedCall.conviction}
                </Badge>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setSelectedCall(null)}>✕</Button>
            </div>
            <div className="flex-1 overflow-auto p-6 space-y-6">
              {/* Trade Details */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Card>
                  <CardContent className="p-4">
                    <p className="text-sm text-text-secondary">Entry</p>
                    <p className="text-2xl font-bold text-text-primary">{selectedCall.entry ? `$${selectedCall.entry.toFixed(2)}` : '—'}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4">
                    <p className="text-sm text-text-secondary">Stop Loss</p>
                    <p className="text-2xl font-bold text-accent-danger">{selectedCall.stop ? `$${selectedCall.stop.toFixed(2)}` : '—'}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4">
                    <p className="text-sm text-text-secondary">Target</p>
                    <p className="text-2xl font-bold text-accent-success">{selectedCall.target ? `$${selectedCall.target.toFixed(2)}` : '—'}</p>
                  </CardContent>
                </Card>
              </div>

              {/* R:R */}
              {selectedCall.entry && selectedCall.stop && selectedCall.target && (
                <Card>
                  <CardContent className="p-4">
                    <p className="text-sm text-text-secondary">Risk:Reward</p>
                    <p className="text-2xl font-bold text-accent-warning">
                      {(() => { const risk = selectedCall.entry! - selectedCall.stop!; const reward = selectedCall.target! - selectedCall.entry!; return risk > 0 ? `${(reward / risk).toFixed(1)}` : '—'; })()}
                    </p>
                  </CardContent>
                </Card>
              )}

              {/* Thesis */}
              {selectedCall.thesis && (
                <Card>
                  <CardHeader>
                    <CardTitle>Investment Thesis</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-text-secondary whitespace-pre-wrap">{selectedCall.thesis}</p>
                  </CardContent>
                </Card>
              )}

              {/* Risks */}
              {selectedCall.risks && selectedCall.risks.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle>Key Risks</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-2">
                      {selectedCall.risks.map((risk, i) => (
                        <li key={i} className="flex items-start gap-2 text-text-secondary">
                          <span className="text-accent-danger">▲</span>
                          <span>{risk}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}

              {/* Technical Details */}
              {selectedCall.technical && (
                <Card>
                  <CardHeader>
                    <CardTitle>Technical Analysis</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <pre className="text-sm text-text-secondary overflow-auto max-h-64">
                      {JSON.stringify(selectedCall.technical, null, 2)}
                    </pre>
                  </CardContent>
                </Card>
              )}

              {/* Fundamental Details */}
              {selectedCall.fundamental && (
                <Card>
                  <CardHeader>
                    <CardTitle>Fundamental Metrics</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <pre className="text-sm text-text-secondary overflow-auto max-h-64">
                      {JSON.stringify(selectedCall.fundamental, null, 2)}
                    </pre>
                  </CardContent>
                </Card>
              )}

              {/* Entry Signal */}
              {selectedCall.entry_signal && (
                <Card>
                  <CardHeader>
                    <CardTitle>Entry Signal</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <pre className="text-sm text-text-secondary overflow-auto max-h-64">
                      {JSON.stringify(selectedCall.entry_signal, null, 2)}
                    </pre>
                  </CardContent>
                </Card>
              )}
            </div>
            <div className="p-6 border-t border-border-color flex justify-end gap-3">
              <Button variant="outline" onClick={() => setSelectedCall(null)}>Close</Button>
              <Button onClick={() => window.open(`https://finance.yahoo.com/quote/${selectedCall.ticker}`, '_blank')}>
                View on Yahoo Finance →
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
