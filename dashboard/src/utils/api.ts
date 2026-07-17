/// <reference types="vite/client" />
// API utilities for communicating with the backend

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

export async function fetchEquityCalls(): Promise<EquityCall[]> {
  const response = await fetch(`${API_BASE}/equity-calls`);
  if (!response.ok) throw new Error('Failed to fetch equity calls');
  return response.json();
}

export async function fetchDashboardData(): Promise<DashboardData> {
  const response = await fetch(`${API_BASE}/dashboard`);
  if (!response.ok) throw new Error('Failed to fetch dashboard data');
  return response.json();
}

export async function fetchStockDetail(ticker: string): Promise<EquityCall> {
  const response = await fetch(`${API_BASE}/stock/${ticker}`);
  if (!response.ok) throw new Error(`Failed to fetch ${ticker}`);
  return response.json();
}

export async function runScan(tickers: string[]): Promise<ScanResult[]> {
  const response = await fetch(`${API_BASE}/scan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tickers }),
  });
  if (!response.ok) throw new Error('Scan failed');
  return response.json();
}

export async function runPipeline(): Promise<PipelineResult> {
  const response = await fetch(`${API_BASE}/pipeline`, {
    method: 'POST',
  });
  if (!response.ok) throw new Error('Pipeline failed');
  return response.json();
}

// Types (duplicate from types for now, could be imported)
export interface EquityCall {
  ticker: string;
  type: 'long_term' | 'swing' | 'sell';
  score: number;
  conviction: 'HIGH' | 'MEDIUM' | 'LOW';
  entry?: number;
  stop?: number;
  target?: number;
  thesis?: string;
  risks?: string[];
  technical?: TechnicalMetrics;
  fundamental?: FundamentalMetrics;
  entry_signal?: EntrySignal;
  timestamp: string;
}

export interface TechnicalMetrics {
  sma_20?: number;
  sma_50?: number;
  sma_200?: number;
  rsi?: number;
  macd?: number;
  macd_signal?: number;
  atr?: number;
  volume_sma?: number;
}

export interface FundamentalMetrics {
  current_ratio?: number;
  debt_to_equity?: number;
  pe_ratio?: number;
  revenue_growth_3y?: number;
  eps_growth_3y?: number;
  rd_intensity?: number;
  roic_3y?: number;
  operating_margin?: number;
  fcf_to_net_income?: number;
  total_score?: number;
  business_quality_score?: number;
  valuation_score?: number;
  financial_risk_score?: number;
  growth_score?: number;
  capital_allocation_score?: number;
}

export interface EntrySignal {
  ticker: string;
  signal: 'BUY' | 'SELL' | 'HOLD' | 'WATCH-LONG' | 'WATCH-SHORT';
  price: number;
  stop_loss: number;
  target: number;
  risk_reward: number;
  conviction: 'HIGH' | 'MEDIUM' | 'LOW';
  pattern?: PatternSignal;
  mtf_aligned: boolean;
  rs_ok: boolean;
  volume_ok: boolean;
  setup_score: number;
}

export interface PatternSignal {
  name: string;
  type: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  entry_zone?: [number, number];
  stop_loss?: number;
  target?: number;
  risk_reward?: number;
}

export interface DashboardData {
  equity_calls: EquityCall[];
  long_term_calls: EquityCall[];
  swing_calls: EquityCall[];
  sell_calls: EquityCall[];
  metadata: {
    last_updated: string;
    universe_size: number;
    scan_duration_seconds: number;
  };
}

export interface ScanResult {
  ticker: string;
  total_score: number;
  graham_score: number;
  fisher_score: number;
  buffett_score: number;
  current_ratio: number;
  debt_to_equity: number;
  pe_ratio: number;
  revenue_growth_3y: number;
  eps_growth_3y: number;
  rd_intensity: number;
  roic_3y: number;
  operating_margin: number;
  fcf_to_net_income: number;
  sector: string;
  industry: string;
  is_disqualified: boolean;
  red_flags: string[];
}

export interface PipelineResult {
  success: boolean;
  phases: string[];
  duration_seconds: number;
  equity_calls_count: number;
}
