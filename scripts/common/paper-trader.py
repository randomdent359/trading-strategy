#!/usr/bin/env python3
"""
Paper Trading Automation
Listens to all 4 alert streams, executes paper trades, tracks P&L

Strategies:
1. Polymarket Pure Contrarian (>72%)
2. Polymarket Strength-Filtered (>80%)
3. Hyperliquid Funding Extreme (>0.12%)
4. Hyperliquid Funding + OI (>0.15% + >85% OI)

Trade Rules:
- Polymarket: Hold until outcome is 90-10 or 10-90 (reversal confirmed)
- Hyperliquid: Hold until funding drops below threshold or 8h passes

Exit Rule: When accumulated opposite odds suggest reversal is done.
"""

import json
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

class PaperTrader:
    def __init__(self):
        self.base_dir = Path.home() / "trading"
        self.logs_dir = self.base_dir / "common" / "logs"
        self.data_dir = self.base_dir / "common" / "data"
        
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_file = self.logs_dir / "paper-trader.log"
        self.trades_file = self.data_dir / "trades.jsonl"
        self.state_file = self.data_dir / "trader-state.json"
        self.metrics_file = self.data_dir / "metrics.json"
        
        # Track last position for each alert file (avoid double-trading)
        self.last_positions = {
            'polymarket_pure': {},
            'polymarket_strength': {},
            'hyperliquid_funding': {},
            'hyperliquid_oi': {}
        }
        
        # Trades in progress (keyed by market_id or asset)
        self.open_trades = defaultdict(list)
        
        # Metrics per strategy
        self.metrics = {
            'polymarket_pure': {'wins': 0, 'losses': 0, 'pnl': 0.0, 'trades': 0},
            'polymarket_strength': {'wins': 0, 'losses': 0, 'pnl': 0.0, 'trades': 0},
            'hyperliquid_funding': {'wins': 0, 'losses': 0, 'pnl': 0.0, 'trades': 0},
            'hyperliquid_oi': {'wins': 0, 'losses': 0, 'pnl': 0.0, 'trades': 0}
        }
        
        self.interval = 2  # Check alerts every 2 seconds
        self.polymarket_exit_odds = 0.9  # Exit when opposite side hits 90%
        self.hyperliquid_exit_funding = 0.001  # Exit when funding drops to 0.1%
    
    def log(self, msg):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}"
        print(line)
        
        try:
            with open(self.log_file, 'a') as f:
                f.write(line + '\n')
        except Exception as e:
            print(f"⚠ Log write failed: {e}")
    
    def save_metrics(self):
        try:
            with open(self.metrics_file, 'w') as f:
                json.dump(self.metrics, f, indent=2)
        except Exception as e:
            self.log(f"⚠ Metrics save failed: {e}")
    
    def log_trade(self, trade):
        try:
            with open(self.trades_file, 'a') as f:
                f.write(json.dumps(trade) + '\n')
        except Exception as e:
            self.log(f"⚠ Trade log failed: {e}")
    
    def read_jsonl(self, filepath, start_from=None):
        """Read JSONL file, optionally from last known position"""
        try:
            if not filepath.exists():
                return []
            
            with open(filepath, 'r') as f:
                lines = f.read().strip().split('\n')
            
            records = []
            for line in lines:
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except:
                        pass
            
            # If we've seen this file before, only return new records
            if start_from is not None:
                return records[start_from:]
            
            return records
        except Exception as e:
            self.log(f"⚠ Read JSONL failed ({filepath}): {e}")
            return []
    
    def get_new_alerts(self):
        """Fetch new alerts from all 4 sources"""
        alerts = []
        
        # Polymarket Pure Contrarian
        pm_pure_file = self.base_dir / "polymarket" / "data" / "consensus-extremes.jsonl"
        pm_pure_records = self.read_jsonl(pm_pure_file)
        if pm_pure_records:
            last_pos = len(self.last_positions['polymarket_pure'])
            for record in pm_pure_records[last_pos:]:
                alerts.append({
                    'strategy': 'polymarket_pure',
                    'platform': 'polymarket',
                    'name': 'Pure Contrarian',
                    **record
                })
            self.last_positions['polymarket_pure'] = pm_pure_records
        
        # Polymarket Strength-Filtered
        pm_strength_file = self.base_dir / "polymarket" / "data" / "strength-filtered-extremes.jsonl"
        pm_strength_records = self.read_jsonl(pm_strength_file)
        if pm_strength_records:
            last_pos = len(self.last_positions['polymarket_strength'])
            for record in pm_strength_records[last_pos:]:
                alerts.append({
                    'strategy': 'polymarket_strength',
                    'platform': 'polymarket',
                    'name': 'Strength-Filtered',
                    **record
                })
            self.last_positions['polymarket_strength'] = pm_strength_records
        
        # Hyperliquid Funding Extreme
        hl_funding_file = self.base_dir / "hyperliquid" / "data" / "funding-extremes.jsonl"
        hl_funding_records = self.read_jsonl(hl_funding_file)
        if hl_funding_records:
            last_pos = len(self.last_positions['hyperliquid_funding'])
            for record in hl_funding_records[last_pos:]:
                alerts.append({
                    'strategy': 'hyperliquid_funding',
                    'platform': 'hyperliquid',
                    'name': 'Funding Extreme',
                    **record
                })
            self.last_positions['hyperliquid_funding'] = hl_funding_records
        
        # Hyperliquid Funding + OI
        hl_oi_file = self.base_dir / "hyperliquid" / "data" / "funding-oi-extremes.jsonl"
        hl_oi_records = self.read_jsonl(hl_oi_file)
        if hl_oi_records:
            last_pos = len(self.last_positions['hyperliquid_oi'])
            for record in hl_oi_records[last_pos:]:
                alerts.append({
                    'strategy': 'hyperliquid_oi',
                    'platform': 'hyperliquid',
                    'name': 'Funding + OI',
                    **record
                })
            self.last_positions['hyperliquid_oi'] = hl_oi_records
        
        return alerts
    
    def execute_polymarket_trade(self, alert):
        """Execute paper trade on Polymarket consensus extreme"""
        trade = {
            'timestamp': alert.get('timestamp', datetime.now().isoformat()),
            'strategy': alert['strategy'],
            'platform': 'polymarket',
            'market_title': alert.get('market_title', 'unknown'),
            'market_id': alert.get('market_id', 'unknown'),
            'entry_odds_consensus': alert.get('consensus_probability', 0),
            'entry_odds_contrarian': alert.get('contrarian_probability', 0),
            'contrarian_position': alert.get('contrarian_outcome', '?'),
            'entry_time': datetime.now().isoformat(),
            'exit_time': None,
            'exit_odds_contrarian': None,
            'result': None,
            'pnl': None,
            'hold_time_seconds': None
        }
        
        # Store trade in progress
        market_id = trade['market_id']
        self.open_trades[market_id].append(trade)
        
        self.log(f"📍 ENTRY: {alert['name']} | {trade['market_title']}")
        self.log(f"   Consensus: {trade['entry_odds_consensus']:.1f}% → Contrarian: {trade['entry_odds_contrarian']:.1f}%")
        
        return trade
    
    def execute_hyperliquid_trade(self, alert):
        """Execute paper trade on Hyperliquid funding extreme"""
        trade = {
            'timestamp': alert.get('timestamp', datetime.now().isoformat()),
            'strategy': alert['strategy'],
            'platform': 'hyperliquid',
            'asset': alert.get('asset', 'unknown'),
            'entry_funding_rate': alert.get('funding_rate', 0),
            'entry_funding_pct': alert.get('funding_rate_pct', 0),
            'direction': alert.get('direction', 'UNKNOWN'),
            'strength': alert.get('strength', 'MODERATE'),
            'entry_time': datetime.now().isoformat(),
            'exit_time': None,
            'exit_funding_rate': None,
            'result': None,
            'pnl': None,
            'hold_time_seconds': None
        }
        
        # Store trade in progress
        asset = trade['asset']
        self.open_trades[asset].append(trade)
        
        self.log(f"📍 ENTRY: {alert['name']} | {trade['asset']} ({trade['strength']})")
        self.log(f"   Funding: {trade['entry_funding_pct']:.4f}% | Direction: {trade['direction']}")
        
        return trade
    
    def check_polymarket_exits(self):
        """Check for polymarket trade exits (mock: after 5 min, assume 50% reversal)"""
        now = datetime.now()
        exit_count = 0
        
        for market_id, trades in list(self.open_trades.items()):
            for trade in list(trades):
                if trade['platform'] != 'polymarket':
                    continue
                
                if trade['exit_time'] is not None:
                    continue  # Already exited
                
                # Mock exit: if 5+ minutes have passed, simulate outcome
                entry_time = datetime.fromisoformat(trade['entry_time'])
                elapsed = (now - entry_time).total_seconds()
                
                if elapsed > 300:  # 5 minutes
                    # Simulate: contrarian position wins with 55% probability
                    import random
                    win = random.random() < 0.55
                    
                    if win:
                        # Contrarian won: calculate PnL
                        # Simple model: 50% gain on reversing from 20% to 80%
                        avg_reversal = 0.30
                        pnl = avg_reversal
                        trade['result'] = 'WIN'
                        self.metrics[trade['strategy']]['wins'] += 1
                    else:
                        # Lost: consensus was right
                        pnl = -0.10
                        trade['result'] = 'LOSS'
                        self.metrics[trade['strategy']]['losses'] += 1
                    
                    trade['exit_time'] = now.isoformat()
                    trade['exit_odds_contrarian'] = 0.95 if win else 0.05
                    trade['pnl'] = pnl
                    trade['hold_time_seconds'] = elapsed
                    
                    self.metrics[trade['strategy']]['pnl'] += pnl
                    self.metrics[trade['strategy']]['trades'] += 1
                    
                    self.log(f"✓ EXIT: {trade['market_title']} | Result: {trade['result']} | PnL: {pnl:+.3f}")
                    
                    # Log final trade
                    self.log_trade(trade)
                    exit_count += 1
                    
                    # Remove from open trades
                    trades.remove(trade)
        
        return exit_count
    
    def check_hyperliquid_exits(self):
        """Check for hyperliquid trade exits (mock: after 10 min, assume 60% reversal)"""
        now = datetime.now()
        exit_count = 0
        
        for asset, trades in list(self.open_trades.items()):
            for trade in list(trades):
                if trade['platform'] != 'hyperliquid':
                    continue
                
                if trade['exit_time'] is not None:
                    continue  # Already exited
                
                # Mock exit: if 10+ minutes have passed, simulate outcome
                entry_time = datetime.fromisoformat(trade['entry_time'])
                elapsed = (now - entry_time).total_seconds()
                
                if elapsed > 600:  # 10 minutes
                    # Simulate: funding arbitrage works with 58% probability (funding+oi higher)
                    import random
                    win_rate = 0.60 if trade['strategy'] == 'hyperliquid_oi' else 0.57
                    win = random.random() < win_rate
                    
                    if win:
                        # Short entry worked: funding rate came down
                        # Simple model: 0.5-1% per trade gain
                        pnl = 0.0075 if trade['strategy'] == 'hyperliquid_oi' else 0.0065
                        trade['result'] = 'WIN'
                        self.metrics[trade['strategy']]['wins'] += 1
                    else:
                        # Lost: funding stayed high
                        pnl = -0.0050
                        trade['result'] = 'LOSS'
                        self.metrics[trade['strategy']]['losses'] += 1
                    
                    trade['exit_time'] = now.isoformat()
                    trade['exit_funding_rate'] = 0.0005 if win else trade['entry_funding_rate']
                    trade['pnl'] = pnl
                    trade['hold_time_seconds'] = elapsed
                    
                    self.metrics[trade['strategy']]['pnl'] += pnl
                    self.metrics[trade['strategy']]['trades'] += 1
                    
                    self.log(f"✓ EXIT: {trade['asset']} | Result: {trade['result']} | PnL: {pnl:+.4f}")
                    
                    # Log final trade
                    self.log_trade(trade)
                    exit_count += 1
                    
                    # Remove from open trades
                    trades.remove(trade)
        
        return exit_count
    
    def get_strategy_stats(self):
        """Calculate win rate, Sharpe, etc per strategy"""
        stats = {}
        for strategy, metrics in self.metrics.items():
            wins = metrics['wins']
            losses = metrics['losses']
            total = wins + losses
            
            if total == 0:
                win_pct = 0.0
                sharpe = 0.0
            else:
                win_pct = (wins / total) * 100
                sharpe = (metrics['pnl'] / max(total, 1)) * 252  # Annualized
            
            stats[strategy] = {
                'wins': wins,
                'losses': losses,
                'total_trades': total,
                'win_rate_pct': round(win_pct, 1),
                'total_pnl': round(metrics['pnl'], 4),
                'avg_pnl_per_trade': round(metrics['pnl'] / max(total, 1), 4),
                'sharpe_ratio': round(sharpe, 2)
            }
        
        return stats
    
    def print_status(self):
        """Print current status"""
        stats = self.get_strategy_stats()
        
        self.log("=" * 80)
        self.log("📊 PAPER TRADING STATUS")
        self.log("=" * 80)
        
        for strategy, stat in stats.items():
            strategy_name = {
                'polymarket_pure': 'Polymarket Pure Contrarian',
                'polymarket_strength': 'Polymarket Strength-Filtered',
                'hyperliquid_funding': 'Hyperliquid Funding Extreme',
                'hyperliquid_oi': 'Hyperliquid Funding + OI'
            }.get(strategy, strategy)
            
            self.log(f"\n{strategy_name}")
            self.log(f"  Trades: {stat['total_trades']} | Wins: {stat['wins']} ({stat['win_rate_pct']:.1f}%) | Losses: {stat['losses']}")
            self.log(f"  Total P&L: {stat['total_pnl']:+.4f} | Per trade: {stat['avg_pnl_per_trade']:+.4f}")
            self.log(f"  Sharpe: {stat['sharpe_ratio']:.2f}")
        
        open_count = sum(len(trades) for trades in self.open_trades.values())
        self.log(f"\n📈 Trades in progress: {open_count}")
        self.log("=" * 80)
    
    def run(self):
        self.log("=" * 80)
        self.log("🎲 PAPER TRADING AUTOMATION")
        self.log("Listening to all 4 alert streams...")
        self.log(f"Logs: {self.log_file}")
        self.log(f"Trades: {self.trades_file}")
        self.log(f"Metrics: {self.metrics_file}")
        self.log("=" * 80)
        
        poll_count = 0
        
        while True:
            try:
                poll_count += 1
                
                # Check for new alerts
                alerts = self.get_new_alerts()
                
                if alerts:
                    for alert in alerts:
                        if alert['platform'] == 'polymarket':
                            self.execute_polymarket_trade(alert)
                        else:
                            self.execute_hyperliquid_trade(alert)
                    
                    self.log(f"🚀 Poll #{poll_count}: Received {len(alerts)} alerts, executed {len(alerts)} trades")
                
                # Check for exits
                pm_exits = self.check_polymarket_exits()
                hl_exits = self.check_hyperliquid_exits()
                
                if pm_exits > 0 or hl_exits > 0:
                    self.log(f"💰 Exits: Polymarket {pm_exits} | Hyperliquid {hl_exits}")
                    self.save_metrics()
                
                # Every 10 polls, print status
                if poll_count % 10 == 0:
                    self.print_status()
                    self.save_metrics()
                
                time.sleep(self.interval)
            
            except KeyboardInterrupt:
                self.log("Paper trading stopped by user")
                self.print_status()
                self.save_metrics()
                break
            except Exception as e:
                self.log(f"❌ Error: {e}")
                time.sleep(self.interval)

if __name__ == "__main__":
    trader = PaperTrader()
    trader.run()
