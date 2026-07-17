import argparse
import logging
import os

from stock_scanner.config import ScannerConfig, load_config_from_file
from stock_scanner.output import (
    generate_markdown_report,
    save_buys_to_excel,
    save_to_csv,
    save_to_markdown,
)
from stock_scanner.scanner import StockScanner


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

def parse_args():
    parser = argparse.ArgumentParser(description="US Stock Fundamental Scanner (V1)")
    parser.add_argument(
        "--config",
        type=str,
        default="config/scanner_config.yaml",
        help="Path to YAML configuration file"
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["market_scan", "single_stock"],
        help="Override execution mode ('market_scan' or 'single_stock')"
    )
    parser.add_argument(
        "--tickers",
        type=str,
        help="Override ticker list (comma-separated, e.g. 'AAPL,MSFT,GOOGL')"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="reports",
        help="Directory to save CSV and Markdown reports"
    )
    return parser.parse_args()

def safe_print(text: str):
    import sys
    try:
        pass
    except UnicodeEncodeError:
        # Fallback to replacing unencodable characters with equivalent representation or '?'
        encoding = sys.stdout.encoding or 'utf-8'
        encoded = text.encode(encoding, errors='replace')
        sys.stdout.buffer.write(encoded + b'\n')

def main():
    setup_logging()
    logger = logging.getLogger("main")

    args = parse_args()

    # 1. Load configuration
    if os.path.exists(args.config):
        logger.info(f"Loading configuration from {args.config}...")
        config = load_config_from_file(args.config)
    else:
        logger.warning(f"Config file {args.config} not found. Using default configuration.")
        config = ScannerConfig()

    # 2. Apply command-line overrides
    if args.mode:
        config.mode = args.mode
    if args.tickers:
        config.tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    logger.info(f"Scanner initialized. Mode: {config.mode}, Tickers: {config.tickers}")

    # 3. Initialize and run scanner
    scanner = StockScanner(config)
    results_df = scanner.run()

    if results_df.empty:
        logger.warning("No results returned by scanner.")
        return

    # 4. Save and export results
    os.makedirs(args.output_dir, exist_ok=True)

    csv_path = os.path.join(args.output_dir, "scan_results.csv")
    md_path = os.path.join(args.output_dir, "scan_report.md")
    xlsx_path = os.path.join(args.output_dir, "buy_recommendations.xlsx")

    save_to_csv(results_df, csv_path)
    save_to_markdown(results_df, md_path, config.mode)
    save_buys_to_excel(results_df, xlsx_path)

    # 5. Print a console preview of the report
    console_report = generate_markdown_report(results_df.head(5), config.mode)
    safe_print("\n" + "="*60)
    safe_print("📋 SCAN RESULTS SUMMARY PREVIEW (Top 5)")
    safe_print("="*60)
    safe_print(console_report)
    safe_print("="*60)
    logger.info(f"Full reports generated in '{args.output_dir}' directory.")

if __name__ == "__main__":
    main()
