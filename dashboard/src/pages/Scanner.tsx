import { FC, useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Table } from '../components/ui/Table';
import { Button } from '../components/ui/Button';
import { Select } from '../components/ui/Select';
import { Input } from '../components/ui/Input';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';

interface ScanResult {
  ticker: string;
  score: number;
  sector: string;
  price: number;
  change_pct: number;
  volume: number;
  pe_ratio: number;
  roic: number;
  debt_to_equity: number;
  current_ratio: number;
  signal: 'BUY' | 'WATCH' | 'HOLD' | 'SELL';
  timestamp: string;
}

export const Scanner: FC = () => {
  const [results, setResults] = useState<ScanResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [scanConfig, setScanConfig] = useState({
    universe: 'sp500',
    min_score: 60,
    min_market_cap: 1000000000,
  });

  useEffect(() => {
    fetchResults();
  }, []);

  const fetchResults = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(scanConfig),
      });
      if (response.ok) {
        const data = await response.json();
        setResults(data.results || []);
      }
    } catch {
      // Fallback
      const fallback = await fetch('/scan_results.json');
      if (fallback.ok) {
        const data = await fallback.json();
        setResults(data.results || []);
      }
    } finally {
      setLoading(false);
    }
  };

  const runScan = () => {
    fetchResults();
  };

  const columns = [
    { key: 'ticker', header: 'Ticker', render: (row: ScanResult) => (
      <div className="flex items-center gap-2">
        <span className="font-mono font-semibold">{row.ticker}</span>
        <Badge variant={row.signal === 'BUY' ? 'success' : row.signal === 'WATCH' ? 'warning' : row.signal === 'SELL' ? 'danger' : 'neutral'} size="sm">
          {row.signal}
        </Badge>
      </div>
    )},
    { key: 'score', header: 'Score', render: (row: ScanResult) => (
      <div className="flex items-center gap-2">
        <span className={`font-mono font-bold ${row.score >= 80 ? 'text-accent-success' : row.score >= 60 ? 'text-accent-warning' : 'text-accent-danger'}`}>
          {row.score.toFixed(1)}
        </span>
        <div className="w-16 h-1.5 bg-bg-tertiary rounded-full overflow-hidden">
          <div className="h-full bg-accent-primary" style={{ width: `${row.score}%` }} />
        </div>
      </div>
    )},
    { key: 'sector', header: 'Sector', render: (row: ScanResult) => row.sector },
    { key: 'price', header: 'Price', render: (row: ScanResult) => `$${row.price.toFixed(2)}` },
    { key: 'change_pct', header: 'Change', render: (row: ScanResult) => (
      <span className={row.change_pct >= 0 ? 'text-accent-success' : 'text-accent-danger'}>
        {row.change_pct >= 0 ? '+' : ''}{row.change_pct.toFixed(2)}%
      </span>
    )},
    { key: 'volume', header: 'Volume', render: (row: ScanResult) => (row.volume / 1e6).toFixed(1) + 'M' },
    { key: 'pe_ratio', header: 'P/E', render: (row: ScanResult) => row.pe_ratio ? row.pe_ratio.toFixed(1) : '—' },
    { key: 'roic', header: 'ROIC', render: (row: ScanResult) => (row.roic * 100).toFixed(1) + '%' },
    { key: 'debt_to_equity', header: 'D/E', render: (row: ScanResult) => row.debt_to_equity.toFixed(2) },
    { key: 'current_ratio', header: 'Current Ratio', render: (row: ScanResult) => row.current_ratio.toFixed(2) },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Stock Scanner</h1>
          <p className="text-text-secondary">Fundamental + Technical screening across universes</p>
        </div>
        <div className="flex items-center gap-3">
          <Select
            value={scanConfig.universe}
            onChange={(e) => setScanConfig(prev => ({ ...prev, universe: e.target.value }))}
            options={[
              { value: 'sp500', label: 'S&P 500' },
              { value: 'nasdaq100', label: 'NASDAQ 100' },
              { value: 'russell2000', label: 'Russell 2000' },
              { value: 'all', label: 'All US Stocks' },
            ]}
            className="w-48"
          />
          <Input
            type="number"
            value={scanConfig.min_score}
            onChange={(e) => setScanConfig(prev => ({ ...prev, min_score: Number(e.target.value) }))}
            placeholder="Min Score"
            className="w-28"
          />
          <Input
            type="number"
            value={scanConfig.min_market_cap / 1e6}
            onChange={(e) => setScanConfig(prev => ({ ...prev, min_market_cap: Number(e.target.value) * 1e6 }))}
            placeholder="Min Mkt Cap (M)"
            className="w-40"
          />
          <Button variant="primary" onClick={runScan} disabled={loading}>
            {loading ? <LoadingSpinner size="sm" /> : '🔍 Run Scan'}
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center h-64">
              <LoadingSpinner size="lg" />
            </div>
          ) : (
            <Table
              data={results}
              columns={columns}
              keyExtractor={(row) => row.ticker}
              striped
              hoverable
              onRowClick={(row) => window.open(`https://finance.yahoo.com/quote/${row.ticker}`, '_blank')}
              emptyMessage="Run a scan to see results"
            />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scan Configuration</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">Min Score</label>
              <Input
                type="number"
                value={scanConfig.min_score}
                onChange={(e) => setScanConfig(prev => ({ ...prev, min_score: Number(e.target.value) }))}
                min={0}
                max={100}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">Min Market Cap (M)</label>
              <Input
                type="number"
                value={scanConfig.min_market_cap / 1e6}
                onChange={(e) => setScanConfig(prev => ({ ...prev, min_market_cap: Number(e.target.value) * 1e6 }))}
                min={0}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">Universe</label>
              <Select
                value={scanConfig.universe}
                onChange={(e) => setScanConfig(prev => ({ ...prev, universe: e.target.value }))}
                options={[
                  { value: 'sp500', label: 'S&P 500' },
                  { value: 'nasdaq100', label: 'NASDAQ 100' },
                  { value: 'russell2000', label: 'Russell 2000' },
                  { value: 'all', label: 'All US Stocks' },
                ]}
              />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
