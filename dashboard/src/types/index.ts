// Core types for the dashboard

export interface Ticker {
  symbol: string;
  name?: string;
  sector?: string;
  industry?: string;
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
  graham_score?: number;
  fisher_score?: number;
  buffett_score?: number;
  total_score?: number;
  business_quality_score?: number;
  valuation_score?: number;
  financial_risk_score?: number;
  growth_score?: number;
  capital_allocation_score?: number;
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

export interface PatternSignal {
  name: string;
  type: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  entry_zone?: [number, number];
  stop_loss?: number;
  target?: number;
  risk_reward?: number;
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

export type TabType = 'dashboard' | 'calls' | 'scanner' | 'backtest';
export type ConvictionLevel = 'HIGH' | 'MEDIUM' | 'LOW';
export type SignalType = 'BUY' | 'SELL' | 'HOLD' | 'WATCH-LONG' | 'WATCH-SHORT';
