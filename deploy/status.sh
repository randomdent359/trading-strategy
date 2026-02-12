#!/bin/bash
# Check status of all trading strategy services on anjie

REMOTE_HOST="rdent@10.3.101.5"

echo "📊 Checking trading strategy services on anjie..."
echo ""

ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'

echo "Service Status:"
echo "═════════════════════════════════════════════════════"
echo ""

sudo systemctl status --no-pager contrarian-monitor 2>/dev/null | grep -E "(Active|Loaded)" || echo "contrarian-monitor: NOT FOUND"
sudo systemctl status --no-pager polymarket-strength-filtered 2>/dev/null | grep -E "(Active|Loaded)" || echo "polymarket-strength-filtered: NOT FOUND"
sudo systemctl status --no-pager hyperliquid-funding 2>/dev/null | grep -E "(Active|Loaded)" || echo "hyperliquid-funding: NOT FOUND"
sudo systemctl status --no-pager hyperliquid-funding-oi 2>/dev/null | grep -E "(Active|Loaded)" || echo "hyperliquid-funding-oi: NOT FOUND"
sudo systemctl status --no-pager paper-trader 2>/dev/null | grep -E "(Active|Loaded)" || echo "paper-trader: NOT FOUND"
sudo systemctl status --no-pager paper-engine 2>/dev/null | grep -E "(Active|Loaded)" || echo "paper-engine: NOT FOUND"

echo ""
echo "Log Files:"
echo "═════════════════════════════════════════════════════"
echo ""

for log in ~/trading/*/logs/*.log; do
  if [ -f "$log" ]; then
    lines=$(wc -l < "$log")
    last=$(tail -1 "$log")
    echo "📄 $(basename $log): $lines lines"
    echo "   Last: $last"
    echo ""
  fi
done

echo "Alert Files:"
echo "═════════════════════════════════════════════════════"
echo ""

for alerts in ~/trading/*/data/*-extremes.jsonl; do
  if [ -f "$alerts" ]; then
    count=$(wc -l < "$alerts")
    echo "🚨 $(basename $alerts): $count alerts"
  fi
done

echo ""
echo "Metrics:"
echo "═════════════════════════════════════════════════════"
echo ""

if [ -f ~/trading/common/data/metrics.json ]; then
  echo "Paper trading metrics:"
  cat ~/trading/common/data/metrics.json | jq '.[]' | head -20
else
  echo "No metrics yet (paper trader not started)"
fi

EOFSH
