"""
Multi-Agent Financial Debate System

Different financial agents debate scores, valuations, and patterns:
- Value Investor (Graham): Safety margin, low P/E, strong balance sheet
- Growth Investor (Fisher): Revenue growth, R&D, competitive moats
- Quality Investor (Buffett): ROIC, margins, FCF conversion, capital allocation
- Technical Analyst: Price patterns, support/resistance, trendlines
- Risk Manager: Red flags, leverage, earnings quality
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AgentPersona(Enum):
    VALUE = "value"  # Graham - margin of safety
    GROWTH = "growth"  # Fisher - growth at reasonable price
    QUALITY = "quality"  # Buffett - compounding machines
    TECHNICAL = "technical"  # Price action, patterns, levels
    RISK = "risk"  # Downside protection


@dataclass
class Argument:
    """A single argument in the debate"""

    agent: AgentPersona
    claim: str
    evidence: str
    confidence: float  # 0-1
    category: str  # "valuation", "quality", "growth", "risk", "technical"


@dataclass
class DebateResult:
    """Result of a debate round"""

    ticker: str
    original_score: float
    adjusted_score: float
    arguments: list[Argument]
    consensus: str  # "bullish", "bearish", "neutral"
    key_points: list[str]


class BaseAgent:
    """Base class for all debate agents"""

    def __init__(self, persona: AgentPersona):
        self.persona = persona
        self.name = persona.value.title()

    def analyze(
        self, metrics: dict[str, Any], technical: dict[str, Any], scores: dict[str, float]
    ) -> list[Argument]:
        """Analyze and produce arguments - override in subclasses"""
        raise NotImplementedError

    def _get_metric(self, metrics: dict[str, Any], key: str, default=None):
        """Safely get metric value"""
        val = metrics.get(key, default)
        try:
            return float(val) if val is not None else default
        except (ValueError, TypeError):
            return default


class ValueInvestorAgent(BaseAgent):
    """
    Benjamin Graham Style: Margin of Safety
    - Low P/E, P/B below 1.5
    - Current ratio > 2
    - Debt/Equity < 0.5
    - Positive earnings track record
    """

    def __init__(self):
        super().__init__(AgentPersona.VALUE)

    def analyze(self, metrics: dict, technical: dict, scores: dict) -> list[Argument]:
        args = []

        pe = self._get_metric(metrics, "pe_ratio")
        self._get_metric(metrics, "price_to_book")
        de = self._get_metric(metrics, "debt_to_equity")
        cr = self._get_metric(metrics, "current_ratio")
        eps_growth = self._get_metric(metrics, "eps_growth_3y")

        # Valuation argument
        if pe and pe < 15:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Attractive P/E of {pe:.1f} provides margin of safety",
                    evidence=f"P/E {pe:.1f} well below market average (~20)",
                    confidence=0.8,
                    category="valuation",
                )
            )
        elif pe and pe > 30:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"P/E of {pe:.1f} is too expensive for value approach",
                    evidence=f"P/E {pe:.1f} exceeds Graham's 15x threshold",
                    confidence=0.85,
                    category="valuation",
                )
            )

        # Balance sheet argument
        if cr and cr > 2.0:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Strong liquidity with current ratio {cr:.2f}",
                    evidence=f"Current ratio {cr:.2f} > 2.0 provides buffer",
                    confidence=0.75,
                    category="risk",
                )
            )
        elif cr and cr < 1.0:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Current ratio {cr:.2f} signals liquidity risk",
                    evidence="Below 1.0 means current liabilities exceed current assets",
                    confidence=0.9,
                    category="risk",
                )
            )

        # Leverage argument
        if de is not None and de < 0.5:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Conservative leverage: D/E of {de:.2f}",
                    evidence="Low debt provides downside protection",
                    confidence=0.8,
                    category="risk",
                )
            )
        elif de is not None and de > 2.0:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Excessive leverage: D/E of {de:.2f}",
                    evidence="High debt increases bankruptcy risk in downturn",
                    confidence=0.9,
                    category="risk",
                )
            )

        # Earnings consistency
        if eps_growth and eps_growth > 0:
            args.append(
                Argument(
                    agent=self.persona,
                    claim="Positive 3-year EPS growth supports valuation",
                    evidence=f"EPS 3Y CAGR: {eps_growth*100:.1f}%",
                    confidence=0.7,
                    category="quality",
                )
            )

        return args


class GrowthInvestorAgent(BaseAgent):
    """
    Philip Fisher Style: Growth at Reasonable Price
    - Revenue growth > 15%
    - R&D intensity > 5%
    - Expanding margins
    - Large TAM with moat
    """

    def __init__(self):
        super().__init__(AgentPersona.GROWTH)

    def analyze(self, metrics: dict, technical: dict, scores: dict) -> list[Argument]:
        args = []

        rev_growth = self._get_metric(metrics, "revenue_growth_3y")
        rd_intensity = self._get_metric(metrics, "rd_intensity")
        op_margin = self._get_metric(metrics, "operating_margin")
        peg = self._get_metric(metrics, "peg_ratio")

        # Revenue growth
        if rev_growth and rev_growth > 0.15:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Strong revenue growth of {rev_growth*100:.1f}% CAGR",
                    evidence="Exceeds 15% threshold for compounding growth",
                    confidence=0.85,
                    category="growth",
                )
            )
        elif rev_growth and rev_growth < 0.05:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Revenue growth {rev_growth*100:.1f}% too slow for growth thesis",
                    evidence="Below 5% suggests mature/declining business",
                    confidence=0.8,
                    category="growth",
                )
            )

        # R&D investment
        if rd_intensity and rd_intensity > 0.05:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"High R&D intensity ({rd_intensity*100:.1f}%) signals innovation investment",
                    evidence="R&D > 5% of revenue indicates future growth optionality",
                    confidence=0.75,
                    category="growth",
                )
            )

        # Margin expansion
        if op_margin and op_margin > 0.20:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Operating margin {op_margin*100:.1f}% shows pricing power",
                    evidence="Margins > 20% indicate competitive moat",
                    confidence=0.8,
                    category="quality",
                )
            )

        # PEG ratio
        if peg and peg < 1.0:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"PEG of {peg:.2f} suggests growth at reasonable price",
                    evidence="PEG < 1.0 = growth cheaper than growth rate",
                    confidence=0.8,
                    category="valuation",
                )
            )
        elif peg and peg > 2.0:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"PEG of {peg:.2f} too expensive for growth profile",
                    evidence="PEG > 2.0 = paying premium for uncertain growth",
                    confidence=0.75,
                    category="valuation",
                )
            )

        return args


class QualityInvestorAgent(BaseAgent):
    """
    Warren Buffett Style: Compounding Quality
    - ROIC > 15%
    - FCF/Net Income > 1.0
    - Consistent ROE > 15%
    - Capital allocation skill (low dilution, buybacks at good prices)
    """

    def __init__(self):
        super().__init__(AgentPersona.QUALITY)

    def analyze(self, metrics: dict, technical: dict, scores: dict) -> list[Argument]:
        args = []

        roic = self._get_metric(metrics, "roic_3y") or self._get_metric(metrics, "roic_3y")
        fcf_ni = self._get_metric(metrics, "fcf_to_net_income")
        roe = None  # roe not in fundamental output
        shares_growth = self._get_metric(metrics, "shares_growth_3y")

        # ROIC
        if roic and roic > 0.15:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Excellent ROIC of {roic*100:.1f}% creates shareholder value",
                    evidence=f"ROIC {roic*100:.1f}% > 15% hurdle = compounding machine",
                    confidence=0.9,
                    category="quality",
                )
            )
        elif roic and roic < 0.10:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"ROIC of {roic*100:.1f}% below cost of capital",
                    evidence="Returns < 10% destroy value over time",
                    confidence=0.85,
                    category="quality",
                )
            )

        # FCF conversion
        if fcf_ni and fcf_ni > 1.0:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"FCF/Net Income {fcf_ni:.2f} - earnings fully cash-backed",
                    evidence="FCF > Net Income = high quality earnings",
                    confidence=0.85,
                    category="quality",
                )
            )
        elif fcf_ni and fcf_ni < 0.5:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Poor FCF conversion ({fcf_ni:.2f}) - earnings not cash-backed",
                    evidence="FCF/Net Income < 0.5 suggests aggressive accounting",
                    confidence=0.8,
                    category="risk",
                )
            )

        # ROE
        if roe and roe > 0.15:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"ROE {roe*100:.1f}% indicates efficient capital deployment",
                    evidence="Consistent ROE > 15% = durable competitive advantage",
                    confidence=0.8,
                    category="quality",
                )
            )

        # Capital allocation - share count
        if shares_growth is not None and shares_growth < -0.02:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Share buybacks reduce count by {abs(shares_growth)*100:.1f}%/yr",
                    evidence="Buybacks at reasonable prices compound per-share value",
                    confidence=0.75,
                    category="quality",
                )
            )
        elif shares_growth is not None and shares_growth > 0.05:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Excessive dilution: shares growing {shares_growth*100:.1f}%/yr",
                    evidence="Dilution > 5%/yr destroys per-share value",
                    confidence=0.8,
                    category="risk",
                )
            )

        return args


class TechnicalAnalystAgent(BaseAgent):
    """
    Technical Analysis: Price Action & Patterns
    - Support/resistance zones
    - Trendlines
    - Volume confirmation
    - Market structure context
    """

    def __init__(self):
        super().__init__(AgentPersona.TECHNICAL)

    def analyze(self, metrics: dict, technical: dict, scores: dict) -> list[Argument]:
        args = []

        if not technical:
            return args

        context = technical.get("context", "Unknown")
        support_zones = technical.get("support_zones", [])
        resistance_zones = technical.get("resistance_zones", [])
        long_term_support = technical.get("long_term_support_trendlines", [])
        long_term_resistance = technical.get("long_term_resistance_trendlines", [])

        # Market context
        if "Bull" in context:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Market structure: {context}",
                    evidence="Higher highs, higher lows - trend is your friend",
                    confidence=0.8,
                    category="technical",
                )
            )
        elif "Bear" in context:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Market structure: {context}",
                    evidence="Lower highs, lower lows - avoid catching falling knives",
                    confidence=0.85,
                    category="technical",
                )
            )

        # Support zones
        if support_zones:
            nearest = support_zones[0]
            price = nearest.get("price", 0)
            strength = nearest.get("strength", 0)
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Key support at ${price:.2f} (strength: {strength})",
                    evidence=f"Tested {nearest.get('touches', 0)} times, volume confirms",
                    confidence=0.75,
                    category="technical",
                )
            )

        # Resistance zones
        if resistance_zones:
            nearest = resistance_zones[0]
            price = nearest.get("price", 0)
            strength = nearest.get("strength", 0)
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Key resistance at ${price:.2f} (strength: {strength})",
                    evidence=f"Rejected {nearest.get('touches', 0)} times, breakout needs volume",
                    confidence=0.75,
                    category="technical",
                )
            )

        # Long-term trendlines
        if long_term_support:
            tl = long_term_support[0]
            args.append(
                Argument(
                    agent=self.persona,
                    claim="Long-term support trendline intact",
                    evidence=f"Slope: {tl.get('slope', 0):.4f}, R^2: {tl.get('r_squared', 0):.2f}",
                    confidence=0.7,
                    category="technical",
                )
            )

        if long_term_resistance:
            tl = long_term_resistance[0]
            args.append(
                Argument(
                    agent=self.persona,
                    claim="Long-term resistance trendline capping upside",
                    evidence=f"Slope: {tl.get('slope', 0):.4f}, R^2: {tl.get('r_squared', 0):.2f}",
                    confidence=0.7,
                    category="technical",
                )
            )

        return args


class RiskManagerAgent(BaseAgent):
    """
    Risk Management: Downside Protection
    - Red flags from fundamental analysis
    - Leverage, earnings quality, liquidity
    - Position sizing based on volatility
    """

    def __init__(self):
        super().__init__(AgentPersona.RISK)

    def analyze(self, metrics: dict, technical: dict, scores: dict) -> list[Argument]:
        args = []

        # Red flags from metrics
        red_flags = metrics.get("red_flags", [])
        if red_flags:
            for flag in red_flags:
                args.append(
                    Argument(
                        agent=self.persona,
                        claim=f"RED FLAG: {flag}",
                        evidence="Fundamental screen detected structural risk",
                        confidence=0.95,
                        category="risk",
                    )
                )

        # Accruals
        accruals = self._get_metric(metrics, "accruals_ratio")
        if accruals and accruals > 0.10:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"High accruals ratio ({accruals:.2f}) - earnings not cash-backed",
                    evidence="Sloan accrual anomaly: high accruals predict lower future returns",
                    confidence=0.85,
                    category="risk",
                )
            )

        # Piotroski
        piotroski = self._get_metric(metrics, "piotroski_f")
        piotroski_max = self._get_metric(metrics, "piotroski_max", 9)
        if piotroski is not None and piotroski_max >= 5:
            if piotroski <= 3:
                args.append(
                    Argument(
                        agent=self.persona,
                        claim=f"Low Piotroski F-Score ({piotroski}/{piotroski_max}) - financial distress risk",
                        evidence="F-Score <= 3 correlates with higher bankruptcy probability",
                        confidence=0.8,
                        category="risk",
                    )
                )
            elif piotroski >= 7:
                args.append(
                    Argument(
                        agent=self.persona,
                        claim=f"Strong Piotroski F-Score ({piotroski}/{piotroski_max}) - financial health improving",
                        evidence="F-Score >= 7 = strong fundamental momentum",
                        confidence=0.8,
                        category="quality",
                    )
                )

        # Revenue stability
        rev_stability = self._get_metric(metrics, "rev_cagr_stability")
        if rev_stability and rev_stability > 0.30:
            args.append(
                Argument(
                    agent=self.persona,
                    claim=f"Unstable revenue growth (stdev: {rev_stability:.2f})",
                    evidence="High revenue volatility increases earnings unpredictability",
                    confidence=0.7,
                    category="risk",
                )
            )

        # Technical risk
        if technical:
            context = technical.get("context", "")
            if "Avoid" in context or "Bear" in context:
                args.append(
                    Argument(
                        agent=self.persona,
                        claim="Technical structure deteriorating - reduce position size",
                        evidence=f"Context: {context}",
                        confidence=0.8,
                        category="risk",
                    )
                )

        return args


class DebateEngine:
    """
    Orchestrates multi-agent debate on stock scores
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.agents = [
            ValueInvestorAgent(),
            GrowthInvestorAgent(),
            QualityInvestorAgent(),
            TechnicalAnalystAgent(),
            RiskManagerAgent(),
        ]

        # Debate parameters
        self.max_rounds = self.config.get("max_rounds", 2)
        self.confidence_threshold = self.config.get("confidence_threshold", 0.7)
        self.score_adjustment_weight = self.config.get("score_adjustment_weight", 0.15)

    def run_debate(self, ticker: str, metrics: dict, technical: dict, scores: dict) -> DebateResult:
        """Run debate for a single ticker"""

        original_score = scores.get("total_score", 50.0)
        all_arguments = []

        # Round 1: Initial arguments from all agents
        for agent in self.agents:
            try:
                args = agent.analyze(metrics, technical, scores)
                all_arguments.extend(args)
            except Exception as e:
                logger.warning(f"Agent {agent.persona.value} failed for {ticker}: {e}")

        # Round 2: Rebuttals (agents respond to opposing views)
        # Simplified: just re-analyze with awareness of other arguments
        for agent in self.agents:
            try:
                # In a real implementation, agents would see other agents' arguments
                # For now, just add emphasis arguments
                pass
            except Exception as e:
                logger.warning(f"Rebuttal failed for {agent.persona.value}: {e}")

        # Calculate score adjustment based on arguments
        adjustment = self._calculate_adjustment(all_arguments, original_score)
        adjusted_score = max(0, min(100, original_score + adjustment))

        # Determine consensus
        consensus = self._determine_consensus(all_arguments, adjusted_score)

        # Extract key points
        key_points = self._extract_key_points(all_arguments)

        return DebateResult(
            ticker=ticker,
            original_score=original_score,
            adjusted_score=adjusted_score,
            arguments=all_arguments,
            consensus=consensus,
            key_points=key_points,
        )

    def _calculate_adjustment(self, arguments: list[Argument], original_score: float) -> float:
        """Calculate score adjustment from debate arguments"""
        if not arguments:
            return 0.0

        total_weight = 0.0
        weighted_adjustment = 0.0

        for arg in arguments:
            if arg.confidence < self.confidence_threshold:
                continue

            # Weight by confidence
            weight = arg.confidence

            # Direction based on category and claim sentiment
            direction = 0
            if arg.category == "valuation":
                if (
                    "attractive" in arg.claim.lower()
                    or "cheap" in arg.claim.lower()
                    or "margin of safety" in arg.claim.lower()
                ):
                    direction = 1
                elif "expensive" in arg.claim.lower() or "too high" in arg.claim.lower():
                    direction = -1
            elif arg.category == "quality":
                if (
                    "excellent" in arg.claim.lower()
                    or "strong" in arg.claim.lower()
                    or "compounding" in arg.claim.lower()
                ):
                    direction = 1
                elif (
                    "poor" in arg.claim.lower()
                    or "below" in arg.claim.lower()
                    or "destroy" in arg.claim.lower()
                ):
                    direction = -1
            elif arg.category == "growth":
                if "strong" in arg.claim.lower() or "exceeds" in arg.claim.lower():
                    direction = 1
                elif "slow" in arg.claim.lower() or "declining" in arg.claim.lower():
                    direction = -1
            elif arg.category == "risk":
                if (
                    "red flag" in arg.claim.lower()
                    or "risk" in arg.claim.lower()
                    or "excessive" in arg.claim.lower()
                    or "distress" in arg.claim.lower()
                ):
                    direction = -1
                elif (
                    "strong" in arg.claim.lower()
                    or "improving" in arg.claim.lower()
                    or "healthy" in arg.claim.lower()
                ):
                    direction = 1
            elif arg.category == "technical":
                if (
                    "bull" in arg.claim.lower()
                    or "support" in arg.claim.lower()
                    or "intact" in arg.claim.lower()
                ):
                    direction = 1
                elif (
                    "bear" in arg.claim.lower()
                    or "resistance" in arg.claim.lower()
                    or "deteriorating" in arg.claim.lower()
                ):
                    direction = -1

            weighted_adjustment += direction * weight * 5.0  # Max 5 points per argument
            total_weight += weight

        if total_weight == 0:
            return 0.0

        # Normalize and cap
        adjustment = (weighted_adjustment / total_weight) * self.score_adjustment_weight * 20
        return max(-15, min(15, adjustment))

    def _determine_consensus(self, arguments: list[Argument], adjusted_score: float) -> str:
        """Determine overall consensus from arguments"""
        if not arguments:
            return "neutral"

        bullish = 0
        bearish = 0

        for arg in arguments:
            if arg.confidence < self.confidence_threshold:
                continue

            # Count sentiment by agent
            if arg.agent in [AgentPersona.VALUE, AgentPersona.GROWTH, AgentPersona.QUALITY]:
                if any(
                    word in arg.claim.lower()
                    for word in [
                        "attractive",
                        "strong",
                        "excellent",
                        "compounding",
                        "growth",
                        "margin of safety",
                        "reasonable",
                        "efficient",
                    ]
                ):
                    bullish += arg.confidence
                elif any(
                    word in arg.claim.lower()
                    for word in [
                        "expensive",
                        "too high",
                        "poor",
                        "risk",
                        "slow",
                        "destroy",
                        "red flag",
                        "distress",
                    ]
                ):
                    bearish += arg.confidence
            elif arg.agent == AgentPersona.TECHNICAL:
                if any(
                    word in arg.claim.lower() for word in ["bull", "support", "intact", "breakout"]
                ):
                    bullish += arg.confidence
                elif any(
                    word in arg.claim.lower()
                    for word in ["bear", "resistance", "deteriorating", "avoid"]
                ):
                    bearish += arg.confidence
            elif arg.agent == AgentPersona.RISK:
                if any(
                    word in arg.claim.lower()
                    for word in ["red flag", "risk", "high", "excessive", "distress", "unstable"]
                ):
                    bearish += arg.confidence * 1.5  # Risk manager weighted more on downside
                elif any(
                    word in arg.claim.lower() for word in ["strong", "improving", "healthy", "low"]
                ):
                    bullish += arg.confidence

        if bullish > bearish * 1.2:
            return "bullish"
        elif bearish > bullish * 1.2:
            return "bearish"
        else:
            return "neutral"

    def _extract_key_points(self, arguments: list[Argument]) -> list[str]:
        """Extract top debate points for summary"""
        # Group by category and take highest confidence
        points = {}
        for arg in arguments:
            if arg.confidence >= self.confidence_threshold:
                key = f"[{arg.category.upper()}] {arg.claim}"
                if key not in points or arg.confidence > points[key][1]:
                    points[key] = (arg.evidence, arg.confidence)

        # Sort by confidence and return top 5
        sorted_points = sorted(points.items(), key=lambda x: -x[1][1])
        return [f"{k}: {v[0]}" for k, v in sorted_points[:5]]

    def run_batch_debate(self, results_df) -> dict[str, DebateResult]:
        """Run debate on all tickers in results DataFrame"""
        debate_results = {}

        for _, row in results_df.iterrows():
            ticker = row["ticker"]

            # Extract metrics dict
            metrics = {k: v for k, v in row.items() if not k.startswith("_")}

            # Extract technical dict
            technical = {}
            for col in [
                "support_zones",
                "resistance_zones",
                "support_trendlines",
                "resistance_trendlines",
                "long_term_support_trendlines",
                "long_term_resistance_trendlines",
                "short_term_support_trendlines",
                "short_term_resistance_trendlines",
                "technical_context",
            ]:
                if col in row and row[col] is not None:
                    technical[col.replace("_", " ")] = row[col]

            if "context" in row:
                technical["context"] = row["context"]

            # Extract scores dict
            scores = {}
            for col in [
                "total_score",
                "business_quality_score",
                "valuation_score",
                "financial_risk_score",
                "growth_score",
                "capital_allocation_score",
            ]:
                if col in row:
                    scores[col] = row[col]

            # Run debate
            result = self.run_debate(ticker, metrics, technical, scores)
            debate_results[ticker] = result
            logger.info(
                f"Debate complete for {ticker}: {result.original_score:.1f} -> {result.adjusted_score:.1f} ({result.consensus})"
            )

        return debate_results


def run_debate_on_results(results_df, config=None) -> dict[str, DebateResult]:
    """
    Run debate on all tickers in results DataFrame
    Returns dict of ticker -> DebateResult
    """
    engine = DebateEngine(config)
    debate_results = {}

    for _, row in results_df.iterrows():
        ticker = row["ticker"]

        # Extract metrics dict (from fundamental analysis)
        metrics = row.to_dict()

        # Extract technical data
        technical = {}
        for col in [
            "support_zones",
            "resistance_zones",
            "support_trendlines",
            "resistance_trendlines",
            "long_term_support_trendlines",
            "long_term_resistance_trendlines",
            "short_term_support_trendlines",
            "short_term_resistance_trendlines",
            "technical_context",
        ]:
            if col in row and row[col] is not None:
                technical[col.replace("_", " ")] = row[col]

        if "context" in row:
            technical["context"] = row["context"]

        # Extract scores dict
        scores = {}
        for col in [
            "total_score",
            "business_quality_score",
            "valuation_score",
            "financial_risk_score",
            "growth_score",
            "capital_allocation_score",
        ]:
            if col in row:
                scores[col] = row[col]

        row.get("total_score", 50)

        # Run debate
        result = engine.run_debate(ticker, metrics, technical, scores)
        debate_results[ticker] = result
        logger.info(
            f"Debate complete for {ticker}: {result.original_score:.1f} -> {result.adjusted_score:.1f} ({result.consensus})"
        )

    return debate_results


def format_debate_output(debate_results: dict[str, DebateResult]) -> str:
    """Format debate results for display"""
    lines = []
    lines.append("=" * 80)
    lines.append("MULTI-AGENT FINANCIAL DEBATE RESULTS")
    lines.append("=" * 80)

    for ticker, result in sorted(debate_results.items(), key=lambda x: -x[1].adjusted_score):
        lines.append("\n" + "-" * 80)
        lines.append(
            f"{ticker} | Original: {result.original_score:.1f} -> Adjusted: {result.adjusted_score:.1f} | Consensus: {result.consensus.upper()}"
        )
        lines.append("-" * 80)

        # Key points
        if result.key_points:
            lines.append("\nKEY DEBATE POINTS:")
            for i, point in enumerate(result.key_points, 1):
                lines.append(f"  {i}. {point}")

        # Arguments by agent
        lines.append("\nAGENT ARGUMENTS:")
        for agent in AgentPersona:
            agent_args = [a for a in result.arguments if a.agent == agent]
            if agent_args:
                lines.append(f"\n  {agent.value.upper()} INVESTOR:")
                for arg in agent_args:
                    lines.append(f"    * [{arg.category.upper()}] {arg.claim}")
                    lines.append(
                        f"      Evidence: {arg.evidence} (confidence: {arg.confidence:.0%})"
                    )

    return "\n".join(lines)
