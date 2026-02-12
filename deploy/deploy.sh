#!/bin/bash
# Deploy trading strategy services to anjie

set -e

# Configuration
REMOTE_HOST="rdent@10.3.101.5"
TRADING_HOME="/home/rdent/trading"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Deploying trading strategy to anjie..."
echo ""

# Create remote directories if needed
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'
mkdir -p ~/trading/{polymarket,hyperliquid,common}/{scripts,logs,data}
mkdir -p ~/trading/systemd
mkdir -p ~/trading/repo
EOFSH

echo "Remote directories created"
echo ""

# --- trading-core package ---
echo "Deploying trading-core package..."
rsync -az --delete \
  -e "ssh -i ~/.ssh/id_ed25519" \
  "${REPO_DIR}/src" "${REPO_DIR}/pyproject.toml" \
  "${REMOTE_HOST}:${TRADING_HOME}/repo/"
echo "Package files synced"

# Deploy config (don't overwrite if already customised)
scp -i ~/.ssh/id_ed25519 "${REPO_DIR}/config.yaml.example" "${REMOTE_HOST}:${TRADING_HOME}/config.yaml.example"
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" \
  "test -f ~/trading/config.yaml || cp ~/trading/config.yaml.example ~/trading/config.yaml"
echo "Config deployed"

# Install/upgrade the package
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'
cd ~/trading/repo
pip install --user --force-reinstall --no-deps . 2>&1
echo "trading-core package installed"
EOFSH

echo ""

# --- Legacy scripts (kept until Stage 2 strategies are verified) ---
echo "Deploying legacy scripts..."
scp -i ~/.ssh/id_ed25519 scripts/polymarket/*.py "${REMOTE_HOST}:${TRADING_HOME}/polymarket/scripts/"
scp -i ~/.ssh/id_ed25519 scripts/hyperliquid/*.py "${REMOTE_HOST}:${TRADING_HOME}/hyperliquid/scripts/"
scp -i ~/.ssh/id_ed25519 scripts/common/*.py "${REMOTE_HOST}:${TRADING_HOME}/common/scripts/"
echo "Legacy scripts deployed"
echo ""

# --- Systemd services ---
echo "Deploying systemd services..."
scp -i ~/.ssh/id_ed25519 systemd/*.service "${REMOTE_HOST}:${TRADING_HOME}/systemd/"
echo "Service files copied"

echo "Installing systemd services..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'

for service in ~/trading/systemd/*.service; do
  service_name=$(basename "$service")
  sudo cp "$service" /etc/systemd/system/
  echo "  $service_name installed"
done

sudo systemctl daemon-reload

for service in ~/trading/systemd/*.service; do
  service_name=$(basename "$service")
  sudo systemctl enable "$service_name" 2>/dev/null
done

EOFSH

echo "Systemd services installed"
echo ""

# --- Permissions ---
echo "Setting permissions..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'
chmod +x ~/trading/polymarket/scripts/*.py 2>/dev/null || true
chmod +x ~/trading/hyperliquid/scripts/*.py 2>/dev/null || true
chmod +x ~/trading/common/scripts/*.py 2>/dev/null || true
EOFSH

echo "Permissions set"
echo ""

# --- Alembic migrations ---
echo "Running database migrations..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'
# Extract TRADING_DATABASE_URL from an installed service file
DB_URL=$(grep -h 'TRADING_DATABASE_URL=' /etc/systemd/system/*.service 2>/dev/null \
  | head -1 \
  | sed 's/.*TRADING_DATABASE_URL=//' \
  | tr -d '"')

if [ -z "$DB_URL" ]; then
  echo "  WARNING: No TRADING_DATABASE_URL found in service files, skipping migrations"
else
  cd ~/trading/repo
  TRADING_DATABASE_URL="$DB_URL" python3 -m alembic \
    -c src/trading_core/migrations/alembic.ini upgrade head 2>&1
  echo "  Migrations complete"
fi
EOFSH

echo ""

# --- Restart active services ---
echo "Restarting services that were running..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'
ALL_SERVICES="hyperliquid-collector polymarket-collector strategy-orchestrator paper-engine contrarian-monitor polymarket-strength-filtered hyperliquid-funding hyperliquid-funding-oi paper-trader"
restarted=""
for svc in $ALL_SERVICES; do
  if sudo systemctl is-active --quiet "$svc" 2>/dev/null; then
    sudo systemctl restart "$svc"
    restarted="$restarted $svc"
    echo "  $svc restarted"
  fi
done
if [ -z "$restarted" ]; then
  echo "  No services were running"
fi
EOFSH

echo ""

# --- Verify ---
echo "Verifying deployment..."
ssh -i ~/.ssh/id_ed25519 "${REMOTE_HOST}" << 'EOFSH'

echo ""
echo "Package version:"
python3 -c "import trading_core; print(f'  trading-core {trading_core.__version__}')" 2>/dev/null || echo "  WARNING: trading-core not importable"

echo ""
echo "Service Status (new services):"
for svc in hyperliquid-collector polymarket-collector strategy-orchestrator paper-engine; do
  status=$(sudo systemctl is-enabled "$svc" 2>/dev/null || echo "not found")
  active=$(sudo systemctl is-active "$svc" 2>/dev/null || echo "inactive")
  echo "  $svc: enabled=$status active=$active"
done

echo ""
echo "Service Status (legacy):"
for svc in contrarian-monitor polymarket-strength-filtered hyperliquid-funding hyperliquid-funding-oi paper-trader; do
  status=$(sudo systemctl is-enabled "$svc" 2>/dev/null || echo "not found")
  active=$(sudo systemctl is-active "$svc" 2>/dev/null || echo "inactive")
  echo "  $svc: enabled=$status active=$active"
done

echo ""
echo "Deployment verification complete"

EOFSH

echo ""
echo "Deployment complete!"
echo ""
echo "Useful commands:"
echo "  View logs:             ssh ${REMOTE_HOST} journalctl -u strategy-orchestrator -f"
echo "  Check status:          ssh ${REMOTE_HOST} sudo systemctl status hyperliquid-collector polymarket-collector strategy-orchestrator"
