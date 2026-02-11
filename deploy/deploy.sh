#!/bin/bash
# Deploy trading strategy services to anjie

set -e

# Configuration
REMOTE_HOST="rdent@10.3.101.5"
TRADING_HOME="/home/rdent/trading"

echo "🚀 Deploying trading strategy to anjie..."
echo ""

# Create remote directories if needed
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'
mkdir -p ~/trading/{polymarket,hyperliquid,common}/{scripts,logs,data}
mkdir -p ~/trading/systemd
EOFSH

echo "✓ Remote directories created"
echo ""

# Deploy Polymarket scripts
echo "📝 Deploying Polymarket scripts..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" "mkdir -p ~/trading/polymarket/scripts"
scp -i ~/.ssh/id_ed25519 scripts/polymarket/*.py "${REMOTE_HOST}:${TRADING_HOME}/polymarket/scripts/"
echo "✓ Polymarket scripts deployed"
echo ""

# Deploy Hyperliquid scripts
echo "📝 Deploying Hyperliquid scripts..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" "mkdir -p ~/trading/hyperliquid/scripts"
scp -i ~/.ssh/id_ed25519 scripts/hyperliquid/*.py "${REMOTE_HOST}:${TRADING_HOME}/hyperliquid/scripts/"
echo "✓ Hyperliquid scripts deployed"
echo ""

# Deploy common scripts
echo "📝 Deploying common scripts..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" "mkdir -p ~/trading/common/scripts"
scp -i ~/.ssh/id_ed25519 scripts/common/*.py "${REMOTE_HOST}:${TRADING_HOME}/common/scripts/"
echo "✓ Common scripts deployed"
echo ""

# Deploy systemd services
echo "📝 Deploying systemd services..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" "mkdir -p ~/trading/systemd"
scp -i ~/.ssh/id_ed25519 systemd/*.service "${REMOTE_HOST}:${TRADING_HOME}/systemd/"
echo "✓ Systemd services deployed"
echo ""

# Install systemd services
echo "🔧 Installing systemd services..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'

for service in ~/trading/systemd/*.service; do
  service_name=$(basename "$service")
  
  # Copy to systemd directory
  sudo cp "$service" /etc/systemd/system/
  
  # Enable service
  sudo systemctl daemon-reload
  sudo systemctl enable "$service_name"
  
  echo "✓ $service_name installed"
done

EOFSH

echo "✓ Systemd services installed"
echo ""

# Set permissions
echo "🔐 Setting permissions..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'

# Make scripts executable
chmod +x ~/trading/polymarket/scripts/*.py
chmod +x ~/trading/hyperliquid/scripts/*.py
chmod +x ~/trading/common/scripts/*.py

# Create log files if they don't exist
mkdir -p ~/trading/polymarket/logs
mkdir -p ~/trading/hyperliquid/logs
mkdir -p ~/trading/common/logs

# Create data directories
mkdir -p ~/trading/polymarket/data
mkdir -p ~/trading/hyperliquid/data
mkdir -p ~/trading/common/data

echo "✓ Permissions set"

EOFSH

echo "✓ Permissions configured"
echo ""

# Verify deployment
echo "✅ Verifying deployment..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'

echo ""
echo "📊 Service Status:"
sudo systemctl status --no-pager contrarian-monitor \
  polymarket-strength-filtered \
  hyperliquid-funding \
  hyperliquid-funding-oi \
  paper-trader 2>/dev/null || true

echo ""
echo "📁 Script Files:"
find ~/trading -name "*.py" -type f | sort

echo ""
echo "✓ Deployment verification complete"

EOFSH

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "Next steps:"
echo "  1. Start individual services: sudo systemctl start <service-name>"
echo "  2. View logs: tail -f ~/trading/<platform>/logs/*.log"
echo "  3. Check status: sudo systemctl status <service-name>"
