#!/bin/bash
# Stop all trading strategy services on anjie

set -e

REMOTE_HOST="rdent@10.3.101.5"

echo "⏹ Stopping all trading strategy services..."
echo ""

ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'

echo "Stopping services..."
echo ""

# Stop in reverse order (trader first, then monitors)
echo "⏹ Stopping paper-trader..."
sudo systemctl stop paper-trader
sleep 1

echo "⏹ Stopping hyperliquid-funding-oi..."
sudo systemctl stop hyperliquid-funding-oi
sleep 1

echo "⏹ Stopping hyperliquid-funding..."
sudo systemctl stop hyperliquid-funding
sleep 1

echo "⏹ Stopping polymarket-strength-filtered..."
sudo systemctl stop polymarket-strength-filtered
sleep 1

echo "⏹ Stopping contrarian-monitor..."
sudo systemctl stop contrarian-monitor

echo ""
echo "✅ All services stopped"
echo ""
echo "Service status:"
sudo systemctl status --no-pager contrarian-monitor \
  polymarket-strength-filtered \
  hyperliquid-funding \
  hyperliquid-funding-oi \
  paper-trader 2>/dev/null || true

EOFSH

echo "✅ All services stopped on anjie"
