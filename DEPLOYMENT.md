# Deployment Guide

## Prerequisites

- SSH access to `rdent@10.3.101.5`
- SSH key at `~/.ssh/id_ed25519`
- Git repository cloned locally
- Linux/Unix environment

## Initial Setup

### 1. Clone Repository

```bash
git clone git@github.com:randomdent359/trading-strategy.git
cd trading-strategy
```

### 2. Verify Files

```bash
# Check all scripts are present
ls -la scripts/polymarket/
ls -la scripts/hyperliquid/
ls -la scripts/common/

# Check systemd services
ls -la systemd/

# Check deployment scripts
ls -la deploy/
```

## Deployment Steps

### Step 1: Deploy All Files

```bash
./deploy/deploy.sh
```

This single command:
- SSHs to anjie
- Creates remote directories
- Copies all Python scripts
- Copies systemd service files
- Installs services
- Sets permissions
- Verifies deployment

**Output:**
```
🚀 Deploying trading strategy to anjie...

✓ Remote directories created
📝 Deploying Polymarket scripts...
✓ Polymarket scripts deployed
...
🎉 Deployment complete!
```

### Step 2: Verify Deployment

```bash
./deploy/status.sh
```

Shows:
- All services loaded and active
- Log file counts
- Alert file counts
- Current metrics

### Step 3: Start Services

#### Option A: Start All at Once

```bash
./deploy/start-all.sh
```

#### Option B: Start Individually

```bash
# Polymarket monitors
ssh rdent@10.3.101.5 "sudo systemctl start contrarian-monitor"
ssh rdent@10.3.101.5 "sudo systemctl start polymarket-strength-filtered"

# Hyperliquid monitors
ssh rdent@10.3.101.5 "sudo systemctl start hyperliquid-funding"
ssh rdent@10.3.101.5 "sudo systemctl start hyperliquid-funding-oi"

# Paper trading engine
ssh rdent@10.3.101.5 "sudo systemctl start paper-trader"
```

### Step 4: Monitor Execution

```bash
# Watch paper trader logs
ssh rdent@10.3.101.5 "tail -f ~/trading/common/logs/paper-trader.log"

# Or use the status script
./deploy/status.sh
```

## Troubleshooting

### Service Won't Start

Check logs:
```bash
ssh rdent@10.3.101.5 "sudo journalctl -u paper-trader -n 50"
```

Verify service file:
```bash
ssh rdent@10.3.101.5 "cat /etc/systemd/system/paper-trader.service"
```

Reload systemd:
```bash
ssh rdent@10.3.101.5 "sudo systemctl daemon-reload"
```

### SSH Connection Failed

Verify SSH key:
```bash
ls -la ~/.ssh/id_ed25519
```

Test SSH connection:
```bash
ssh -i ~/.ssh/id_ed25519 rdent@10.3.101.5 "echo connected"
```

### Scripts Not Found

Verify files were deployed:
```bash
ssh rdent@10.3.101.5 "ls -la ~/trading/common/scripts/"
```

Check if executable:
```bash
ssh rdent@10.3.101.5 "file ~/trading/common/scripts/paper-trader.py"
```

### Logs Not Being Written

Check log directory permissions:
```bash
ssh rdent@10.3.101.5 "ls -la ~/trading/common/logs/"
```

Check if logs have content:
```bash
ssh rdent@10.3.101.5 "tail ~/trading/common/logs/paper-trader.log"
```

## Maintenance

### Redeploying Updated Scripts

When you update a script locally:

```bash
# Update script in repository
vim scripts/common/paper-trader.py

# Redeploy
./deploy/deploy.sh

# Restart service
ssh rdent@10.3.101.5 "sudo systemctl restart paper-trader"
```

### Viewing Metrics

```bash
ssh rdent@10.3.101.5 "cat ~/trading/common/data/metrics.json | jq"
```

### Viewing Recent Trades

```bash
ssh rdent@10.3.101.5 "tail -20 ~/trading/common/data/trades.jsonl | jq"
```

## Automated Deployment (CI/CD)

To automate deployment on git push:

Create `.git/hooks/post-receive` on server:

```bash
#!/bin/bash
# Auto-deploy on push
cd /home/rdent/trading-strategy
git fetch origin
git reset --hard origin/master
./deploy/deploy.sh
./deploy/start-all.sh
```

Or use GitHub Actions (example workflow in `.github/workflows/deploy.yml`).

## Rollback

If deployment fails:

```bash
# Stop all services
./deploy/stop-all.sh

# Check last working version in git
git log --oneline

# Checkout previous version
git checkout <commit-hash>

# Redeploy
./deploy/deploy.sh

# Restart
./deploy/start-all.sh
```

## Post-Deployment

### 1. Verify Dashboard Access

Open browser: `http://10.3.101.5/`
- Click 💰 P&L tab
- Should show paper trading metrics

### 2. Monitor Logs for First Hour

Watch for:
- Initial API calls
- First alert detection
- First trade execution
- Metrics updates

```bash
./deploy/status.sh  # Run periodically
```

### 3. Check Metrics After 24 Hours

```bash
ssh rdent@10.3.101.5 "cat ~/trading/common/data/metrics.json | jq"
```

Expected:
- Multiple trades per strategy
- Win rates accumulating
- P&L positive or near-neutral

## Updating Repository

When you want to push changes back to GitHub:

```bash
cd /home/rdent/trading-strategy

# Make changes to scripts
vim scripts/polymarket/contrarian-monitor.py

# Stage and commit
git add scripts/
git commit -m "Fix contrarian monitor bug"

# Push to GitHub
git push origin master

# Optionally redeploy
./deploy/deploy.sh
```

## Support & Monitoring

### Quick Status Check

```bash
./deploy/status.sh
```

### Real-Time Monitoring

```bash
ssh rdent@10.3.101.5 << 'EOF'
watch -n 5 'echo "=== SERVICES ===" && \
  sudo systemctl status --no-pager paper-trader | grep Active && \
  echo "=== RECENT LOGS ===" && \
  tail -3 ~/trading/common/logs/paper-trader.log && \
  echo "=== METRICS ===" && \
  cat ~/trading/common/data/metrics.json | jq ".[] | {trades, wins, pnl}"'
EOF
```

### Long-Running Deployment

For long operations, use screen/tmux:

```bash
ssh rdent@10.3.101.5
tmux new-session -d -s trading
tmux send-keys -t trading "tail -f ~/trading/common/logs/paper-trader.log" Enter
tmux attach-session -t trading
```

---

**Quick Reference:**
- Deploy: `./deploy/deploy.sh`
- Start: `./deploy/start-all.sh`
- Stop: `./deploy/stop-all.sh`
- Status: `./deploy/status.sh`
- Logs: `ssh rdent@10.3.101.5 "tail -f ~/trading/common/logs/paper-trader.log"`
