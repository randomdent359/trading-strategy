# Trading Strategy - Deployment Repository

Complete Python scripts and systemd services for contrarian trading strategy execution across Polymarket and Hyperliquid.

## Repository Structure

```
trading-strategy/
├── scripts/
│   ├── polymarket/
│   │   ├── contrarian-monitor.py      (>72% consensus extremes)
│   │   └── strength-filtered-monitor.py (>80% consensus only)
│   ├── hyperliquid/
│   │   ├── funding-monitor.py         (>0.12% funding rate)
│   │   └── funding-oi-monitor.py      (>0.15% funding + OI extreme)
│   └── common/
│       └── paper-trader.py            (paper trading automation)
├── systemd/
│   ├── contrarian-monitor.service
│   ├── polymarket-strength-filtered.service
│   ├── hyperliquid-funding.service
│   ├── hyperliquid-funding-oi.service
│   └── paper-trader.service
└── deploy/
    ├── deploy.sh                      (deploy all to anjie)
    ├── start-all.sh                   (start all services)
    ├── stop-all.sh                    (stop all services)
    └── status.sh                      (check service status)
```

## What Each Component Does

### Monitors

**Polymarket Contrarian Monitor** (`contrarian-monitor.py`)
- Polls Polymarket API every 30 seconds
- Detects consensus extremes (>72%)
- Writes alerts to `consensus-extremes.jsonl`
- Target: 54% win rate

**Polymarket Strength-Filtered Monitor** (`strength-filtered-monitor.py`)
- Polls Polymarket API every 30 seconds
- Detects strong extremes (>80% only, skips 72-80%)
- Writes alerts to `strength-filtered-extremes.jsonl`
- Target: 56% win rate

**Hyperliquid Funding Monitor** (`funding-monitor.py`)
- Polls Hyperliquid API every 60 seconds
- Detects funding rate extremes (>0.12%)
- Writes alerts to `funding-extremes.jsonl`
- Target: 57% win rate

**Hyperliquid Funding+OI Monitor** (`funding-oi-monitor.py`)
- Polls Hyperliquid API every 60 seconds
- Detects dual extremes (funding >0.15% + OI >85%)
- Writes alerts to `funding-oi-extremes.jsonl`
- Target: 60% win rate

### Paper Trading Engine

**Paper Trader** (`paper-trader.py`)
- Polls all 4 alert files every 2 seconds
- Detects new alerts (not previously seen)
- Executes paper trade entry on alert
- Holds trade 5-10 minutes
- Simulates exit based on strategy win rates
- Logs results to `trades.jsonl`
- Updates metrics in `metrics.json`

## Quick Start

### 1. Deploy to anjie

```bash
cd /home/rdent/trading-strategy
./deploy/deploy.sh
```

This will:
- Copy all scripts to `~/trading/{polymarket,hyperliquid,common}/scripts/`
- Copy systemd services to `~/trading/systemd/`
- Install services in `/etc/systemd/system/`
- Set permissions and create log directories

### 2. Start all services

```bash
./deploy/start-all.sh
```

Or start individually:
```bash
ssh rdent@10.3.101.5 "sudo systemctl start contrarian-monitor"
ssh rdent@10.3.101.5 "sudo systemctl start polymarket-strength-filtered"
ssh rdent@10.3.101.5 "sudo systemctl start hyperliquid-funding"
ssh rdent@10.3.101.5 "sudo systemctl start hyperliquid-funding-oi"
ssh rdent@10.3.101.5 "sudo systemctl start paper-trader"
```

### 3. Monitor status

```bash
./deploy/status.sh
```

Or:
```bash
ssh rdent@10.3.101.5 "sudo systemctl status paper-trader"
ssh rdent@10.3.101.5 "tail -f ~/trading/common/logs/paper-trader.log"
```

## Deployment Details

### Deployment Script (`deploy.sh`)

```bash
./deploy/deploy.sh
```

**What it does:**
1. Creates remote directories on anjie
2. Deploys Python scripts to correct locations
3. Deploys systemd service files
4. Installs services in `/etc/systemd/system/`
5. Enables services for auto-start
6. Sets file permissions
7. Creates log and data directories
8. Verifies deployment

**SSH Key Required:**
- Uses `~/.ssh/id_ed25519` for passwordless auth to `rdent@10.3.101.5`
- Services run as `rdent` user

### Start All Services (`start-all.sh`)

```bash
./deploy/start-all.sh
```

Starts services in order:
1. contrarian-monitor
2. polymarket-strength-filtered
3. hyperliquid-funding
4. hyperliquid-funding-oi
5. paper-trader

### Stop All Services (`stop-all.sh`)

```bash
./deploy/stop-all.sh
```

Stops services in reverse order (trader first, then monitors).

### Check Status (`status.sh`)

```bash
./deploy/status.sh
```

Shows:
- Active/Running status of all services
- Log file sizes and last entry
- Alert counts per strategy
- Live paper trading metrics

## File Locations on anjie

After deployment, files are organized as:

```
~/trading/
├── polymarket/
│   ├── scripts/
│   │   ├── contrarian-monitor.py
│   │   └── strength-filtered-monitor.py
│   ├── logs/
│   │   ├── contrarian-monitor.log
│   │   └── strength-filtered-monitor.log
│   └── data/
│       ├── consensus-extremes.jsonl
│       ├── strength-filtered-extremes.jsonl
│       ├── monitor-state.json
│       └── strength-filtered-state.json
├── hyperliquid/
│   ├── scripts/
│   │   ├── funding-monitor.py
│   │   └── funding-oi-monitor.py
│   ├── logs/
│   │   ├── funding-monitor.log
│   │   └── funding-oi-monitor.log
│   └── data/
│       ├── funding-extremes.jsonl
│       ├── funding-oi-extremes.jsonl
│       ├── monitor-state.json
│       └── funding-oi-state.json
├── common/
│   ├── scripts/
│   │   └── paper-trader.py
│   ├── logs/
│   │   └── paper-trader.log
│   └── data/
│       ├── metrics.json
│       ├── trades.jsonl
│       └── trader-state.json
└── systemd/
    ├── contrarian-monitor.service
    ├── polymarket-strength-filtered.service
    ├── hyperliquid-funding.service
    ├── hyperliquid-funding-oi.service
    └── paper-trader.service
```

Services are installed to `/etc/systemd/system/` and enabled for auto-start on reboot.

## System Service Management

Once deployed, services are managed via systemctl on anjie:

```bash
# Check status
sudo systemctl status contrarian-monitor

# Start service
sudo systemctl start contrarian-monitor

# Stop service
sudo systemctl stop contrarian-monitor

# Restart service
sudo systemctl restart contrarian-monitor

# Enable for auto-start
sudo systemctl enable contrarian-monitor

# View logs
sudo journalctl -u contrarian-monitor -f
```

## Data Files

### Alert JSONL Files

Each monitor writes alerts to JSONL format (one alert per line):

```json
{
  "timestamp": "2026-02-11T15:05:00Z",
  "market_title": "ETH Up Next 5m",
  "consensus_outcome": "UP",
  "consensus_probability": 82.5,
  "contrarian_outcome": "DOWN",
  "contrarian_probability": 17.5,
  "strength": "EXTREME"
}
```

### Metrics JSON

Paper trader updates metrics every time a trade exits:

```json
{
  "polymarket_pure": {
    "wins": 5,
    "losses": 2,
    "pnl": 0.125,
    "trades": 7
  },
  "polymarket_strength": { ... },
  "hyperliquid_funding": { ... },
  "hyperliquid_oi": { ... }
}
```

### Trades Log

Detailed trade history in JSONL format:

```json
{
  "timestamp": "2026-02-11T15:05:00Z",
  "strategy": "polymarket_pure",
  "result": "WIN",
  "pnl": 0.30,
  "hold_time_seconds": 300
}
```

## Monitoring & Troubleshooting

### View Live Logs

```bash
ssh rdent@10.3.101.5 "tail -f ~/trading/polymarket/logs/contrarian-monitor.log"
ssh rdent@10.3.101.5 "tail -f ~/trading/common/logs/paper-trader.log"
```

### Check for Errors

```bash
ssh rdent@10.3.101.5 "sudo journalctl -u contrarian-monitor -n 50"
ssh rdent@10.3.101.5 "sudo journalctl -u paper-trader -n 50"
```

### Restart Service

```bash
ssh rdent@10.3.101.5 "sudo systemctl restart paper-trader"
```

### View Metrics

```bash
ssh rdent@10.3.101.5 "cat ~/trading/common/data/metrics.json | jq"
```

## Requirements

- Python 3.7+
- `curl` command-line tool
- SSH access to `rdent@10.3.101.5`
- SSH key at `~/.ssh/id_ed25519` for passwordless auth
- Linux/Unix environment for running scripts

## Integration with Dashboard

These scripts write data that feeds the live dashboard:

```
http://10.3.101.5/ → 💰 P&L tab
```

The dashboard reads:
- `metrics.json` - Live strategy metrics
- `trades.jsonl` - Trade history
- `*-extremes.jsonl` - Strategy alerts

And displays:
- Real-time P&L per strategy
- Win rate and trade count
- Detailed trades log
- Edge confirmation status

## Support

For issues:
1. Check logs: `tail -f ~/trading/*/logs/*.log`
2. Verify services: `sudo systemctl status <service-name>`
3. Check remote connectivity: `ssh rdent@10.3.101.5 "ls -la ~/trading"`
4. Review API endpoints: scripts attempt Polymarket/Hyperliquid APIs

## License

Internal use only. Do not redistribute.
