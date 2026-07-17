import { FC, useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { Table } from '../components/ui/Table';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';

interface BacktestResult {
  phase: number;
  start_date: string;
  end_date: string;
  tickers: string[];
  portfolio_return: number;
  benchmark_return: number;
  alpha: number;
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  total_trades: number;
  avg_holding_days: number;
  timestamp: string;
}

export const Backtest: FC = () => {
  const [results, setResults] = useState<BacktestResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [config, setConfig] = useState({
    phases: 3,
    start_year: 2021,
    tickers_per_phase: 20,
    rebalance_days: 30,
  });

  useEffect(() => {
    fetchResults();
  }, []);

  const fetchResults = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      if (response.ok) {
        const data = await response.json();
        setResults(data.results || []);
      }
    } catch {
      const fallback = await fetch('/backtest_results.json');
      if (fallback.ok) {
        const data = await fallback.json();
        setResults(data.results || []);
      }
    } finally {
      setLoading(false);
    }
  };

  const runBacktest = () => {
    fetchResults();
  };

  // Summary stats
  const totalReturn = results.reduce((sum, r) => sum + r.portfolio_return, 0) / (results.length || 1);
  const totalAlpha = results.reduce((sum, r) => sum + r.alpha, 0) / (results.length || 1);
  const avgSharpe = results.reduce((sum, r) => sum + r.sharpe, 0) / (results.length || 1);
  const avgWinRate = results.reduce((sum, r) => sum + r.win_rate, 0) / (results.length || 1);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Backtest Engine</h1>
          <p className="text-text-secondary">Historical simulation with point-in-time data</p>
        </div>
        <Button variant="primary" onClick={runBacktest} disabled={loading}>
          {loading ? <LoadingSpinner size="sm" /> : '▶ Run Backtest'}
        </Button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-text-secondary">Avg Portfolio Return</p>
            <p className="text-2xl font-bold {totalReturn >= 0 ? 'text-accent-success' : 'text-accent-danger'}">
              {totalReturn >= 0 ? '+' : ''}{totalReturn.toFixed(2)}%
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-text-secondary">Avg Alpha vs Benchmark</p>
            <p className="text-2xl font-bold {totalAlpha >= 0 ? 'text-accent-success' : 'text-accent-danger'}">
              {totalAlpha >= 0 ? '+' : ''}{totalAlpha.toFixed(2)}%
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-text-secondary">Avg Sharpe Ratio</p>
            <p className="text-2xl font-bold text-text-primary">{avgSharpe.toFixed(2)}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-sm text-text-secondary">Avg Win Rate</p>
            <p className="text-2xl font-bold text-text-primary">{avgWinRate.toFixed(1)}%</p>
          </CardContent>
        </Card>
      </div>

      {/* Configuration */}
      <Card>
        <CardHeader>
          <CardTitle>Backtest Configuration</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">Phases</label>
              <Input
                type="number"
                value={config.phases}
                onChange={(e) => setConfig(prev => ({ ...prev, phases: Number(e.target.value) }))}
                min={1}
                max={10}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">Start Year</label>
              <Input
                type="number"
                value={config.start_year}
                onChange={(e) => setConfig(prev => ({ ...prev, start_year: Number(e.target.value) }))}
                min={2010}
                max={new Date().getFullYear() - 1}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">Tickers per Phase</label>
              <Input
                type="number"
                value={config.tickers_per_phase}
                onChange={(e) => setConfig(prev => ({ ...prev, tickers_per_phase: Number(e.target.value) }))}
                min={5}
                max={100}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">Rebalance Days</label>
              <Input
                type="number"
                value={config.rebalance_days}
                onChange={(e) => setConfig(prev => ({ ...prev, rebalance_days: Number(e.target.value) }))}
                min={7}
                max={365}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Phase Results</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-64">
              <LoadingSpinner size="lg" />
            </div>
          ) : (
            <Table
              data={results}
              columns={[
                { key: 'phase', header: 'Phase' },
                { key: 'start_date', header: 'Start' },
                { key: 'end_date', header: 'End' },
                { key: 'tickers', header: 'Tickers', render: (row: BacktestResult) => `${row.tickers.length}` },
                { key: 'portfolio_return', header: 'Portfolio', render: (row: BacktestResult) => (
                  <span className={row.portfolio_return >= 0 ? 'text-accent-success' : 'text-accent-danger'}>
                    {row.portfolio_return >= 0 ? '+' : ''}{row.portfolio_return.toFixed(2)}%
                  </span>
                )},
                { key: 'benchmark_return', header: 'Benchmark', render: (row: BacktestResult) => (
                  <span className={row.benchmark_return >= 0 ? 'text-accent-success' : 'text-accent-danger'}>
                    {row.benchmark_return >= 0 ? '+' : ''}{row.benchmark_return.toFixed(2)}%
                  </span>
                )},
                { key: 'alpha', header: 'Alpha', render: (row: BacktestResult) => (
                  <span className={row.alpha >= 0 ? 'text-accent-success' : 'text-accent-danger'}>
                    {row.alpha >= 0 ? '+' : ''}{row.alpha.toFixed(2)}%
                  </span>
                )},
                { key: 'sharpe', header: 'Sharpe', render: (row: BacktestResult) => row.sharpe.toFixed(2) },
                { key: 'max_drawdown', header: 'Max DD', render: (row: BacktestResult) => (
                  <span className="text-accent-danger">{row.max_drawdown.toFixed(2)}%</span>
                )},
                { key: 'win_rate', header: 'Win Rate', render: (row: BacktestResult) => `${row.win_rate.toFixed(1)}%` },
                { key: 'total_trades', header: 'Trades', render: (row: BacktestResult) => `${row.total_trades}` },
                { key: 'avg_holding_days', header: 'Avg Hold', render: (row: BacktestResult) => `${row.avg_holding_days}d` },
              ]}
              keyExtractor={(row) => `phase-${row.phase}`}
              striped
              hoverable
              emptyMessage="Run a backtest to see results"
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
};
