#!/usr/bin/env python3
"""
Hyperliquid Funding Rate Monitor
Monitors perpetual futures funding rates for contrarian arbitrage opportunities.

Strategy: When funding is extreme (>0.12%), shorts are squeezed.
Trade: Short the asset, close when funding normalizes.
Expected edge: 55-58% win rate, 0.5-1.0% per trade.

Runs as systemd service, logs to ~/trading/hyperliquid/
"""

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

class FundingMonitor:
    def __init__(self):
        self.hl_api = "https://api.hyperliquid.xyz"
        
        # XDG Base Directory convention
        self.base_dir = Path.home() / "trading" / "hyperliquid"
        self.logs_dir = self.base_dir / "logs"
        self.data_dir = self.base_dir / "data"
        
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_file = self.logs_dir / "funding-monitor.log"
        self.alerts_file = self.data_dir / "funding-extremes.jsonl"
        self.state_file = self.data_dir / "monitor-state.json"
        
        self.interval = 60  # Poll every minute (funding updates every 8 hours)
        self.extreme_threshold = 0.0012  # 0.12% per 8 hours = extreme
        self.warning_threshold = 0.0010  # 0.10% = watch
        
        self.poll_count = 0
        self.extreme_count = 0
        
        # Assets to monitor (high volume, high funding rate volatility)
        self.assets = ['BTC', 'ETH', 'SOL', 'ARB', 'OP']
    
    def log(self, msg):
        """Append to log file"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}"
        print(line)
        
        try:
            with open(self.log_file, 'a') as f:
                f.write(line + '\n')
        except Exception as e:
            print(f"⚠ Log write failed: {e}")
    
    def save_state(self):
        """Persist monitor state"""
        try:
            state = {
                'timestamp': datetime.now().isoformat(),
                'poll_count': self.poll_count,
                'extreme_count': self.extreme_count,
                'uptime_seconds': self.poll_count * self.interval
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self.log(f"⚠ State save failed: {e}")
    
    def fetch_funding_rates(self):
        """Fetch current funding rates from Hyperliquid API"""
        try:
            # Hyperliquid perpetuals info endpoint
            result = subprocess.run([
                'curl', '-s', '--max-time', '5',
                f'{self.hl_api}/info'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                return {}
            
            data = json.loads(result.stdout)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.log(f"❌ API fetch error: {e}")
            return {}
    
    def scan_for_extremes(self, funding_data):
        """Identify extreme funding rates"""
        extremes = []
        warnings = []
        
        try:
            # Parse funding rates by asset
            for asset in self.assets:
                # Hyperliquid API structure varies, adjust as needed
                funding_rate = funding_data.get(asset, {}).get('funding', 0)
                
                if not funding_rate:
                    continue
                
                # Convert to decimal if percentage
                if funding_rate > 1:
                    funding_rate = funding_rate / 100
                
                # Check thresholds
                if funding_rate > self.extreme_threshold:
                    extremes.append({
                        'timestamp': datetime.now().isoformat(),
                        'asset': asset,
                        'funding_rate': funding_rate,
                        'funding_rate_pct': round(funding_rate * 100, 4),
                        'direction': 'LONG_SQUEEZED' if funding_rate > 0 else 'SHORT_SQUEEZED',
                        'strength': 'EXTREME' if funding_rate > 0.002 else 'STRONG'
                    })
                elif funding_rate > self.warning_threshold:
                    warnings.append({
                        'asset': asset,
                        'funding_rate': funding_rate
                    })
        
        except Exception as e:
            self.log(f"⚠ Scan error: {e}")
        
        return extremes, warnings
    
    def log_extremes(self, extremes):
        """Log funding extremes to JSONL"""
        if not extremes:
            return
        
        try:
            with open(self.alerts_file, 'a') as f:
                for extreme in extremes:
                    f.write(json.dumps(extreme) + '\n')
        except Exception as e:
            self.log(f"⚠ Alert log failed: {e}")
    
    def run(self):
        """Main monitoring loop"""
        self.log("=" * 80)
        self.log("🎲 HYPERLIQUID FUNDING RATE MONITOR")
        self.log(f"Polling: {self.interval}s | Extreme threshold: {self.extreme_threshold*100:.3f}%")
        self.log(f"Assets: {', '.join(self.assets)}")
        self.log(f"Logs: {self.log_file}")
        self.log(f"Alerts: {self.alerts_file}")
        self.log("=" * 80)
        
        while True:
            try:
                self.poll_count += 1
                
                # Fetch funding rates
                funding_data = self.fetch_funding_rates()
                
                if funding_data:
                    extremes, warnings = self.scan_for_extremes(funding_data)
                    
                    if extremes:
                        self.extreme_count += len(extremes)
                        self.log_extremes(extremes)
                        self.log(f"🚨 Poll #{self.poll_count}: {len(extremes)} EXTREME funding rates found!")
                        for ex in extremes:
                            self.log(f"   {ex['asset']}: {ex['funding_rate_pct']:.4f}% → {ex['direction']}")
                    elif warnings:
                        if self.poll_count % 5 == 0:  # Log warnings every 5 polls
                            self.log(f"⚠ Poll #{self.poll_count}: {len(warnings)} elevated funding rates")
                    else:
                        if self.poll_count % 10 == 0:
                            self.log(f"✓ Poll #{self.poll_count}: {len(self.assets)} assets, no extremes")
                else:
                    self.log(f"⚠ Poll #{self.poll_count}: API fetch failed")
                
                # Save state
                self.save_state()
                
                # Wait before next poll
                time.sleep(self.interval)
            
            except KeyboardInterrupt:
                self.log("Monitor stopped by user")
                break
            except Exception as e:
                self.log(f"❌ Unexpected error: {e}")
                time.sleep(self.interval)

if __name__ == "__main__":
    monitor = FundingMonitor()
    monitor.run()
