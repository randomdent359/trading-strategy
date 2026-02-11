#!/bin/bash
# Start all trading strategy services on anjie

set -e

REMOTE_HOST="rdent@10.3.101.5"

echo "🚀 Starting all trading strategy services..."
echo ""

ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'

echo "Starting services..."
echo ""

# Start Polymarket Pure Contrarian
echo "▶ Starting contrarian-monitor..."
sudo systemctl start contrarian-monitor
sleep 1

# Start Polymarket Strength-Filtered
echo "▶ Starting polymarket-strength-filtered..."
sudo systemctl start polymarket-strength-filtered
sleep 1

# Start Hyperliquid Funding
echo "▶ Starting hyperliquid-funding..."
sudo systemctl start hyperliquid-funding
sleep 1

# Start Hyperliquid Funding+OI
echo "▶ Starting hyperliquid-funding-oi..."
sudo systemctl start hyperliquid-funding-oi
sleep 1

# Start Paper Trader
echo "▶ Starting paper-trader..."
sudo systemctl start paper-trader
sleep 1

echo ""
echo "✅ All services started"
echo ""
echo "Service status:"
sudo systemctl status --no-pager contrarian-monitor \
  polymarket-strength-filtered \
  hyperliquid-funding \
  hyperliquid-funding-oi \
  paper-trader 2>/dev/null || true

echo ""
echo "Tip: Watch logs with:"
echo "  tail -f ~/trading/common/logs/paper-trader.log"

EOFSH

echo "✅ All services started on anjie"
