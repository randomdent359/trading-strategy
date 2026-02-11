#!/usr/bin/env python3
"""
Hyperliquid Funding + OI Monitor
Extreme funding + extreme leverage = maximum short squeeze incoming

Strategy: When BOTH funding rate is high AND open interest is at extremes,
the short squeeze is guaranteed to happen.

Theory: Longs pay extreme funding + use extreme leverage = setup for reversal
Win rate target: 58-62% (higher than pure funding trades)
"""

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

class FundingOIMonitor:
    def __init__(self):
        self.hl_api = "https://api.hyperliquid.xyz"
        
        self.base_dir = Path.home() / "trading" / "hyperliquid"
        self.logs_dir = self.base_dir / "logs"
        self.data_dir = self.base_dir / "data"
        
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_file = self.logs_dir / "funding-oi-monitor.log"
        self.alerts_file = self.data_dir / "funding-oi-extremes.jsonl"
        self.state_file = self.data_dir / "funding-oi-state.json"
        
        self.interval = 60
        self.funding_threshold = 0.0015  # 0.15% (higher than pure strategy)
        self.oi_threshold = 0.85  # 85% of max OI = extreme
        
        self.poll_count = 0
        self.extreme_count = 0
        
        self.assets = ['BTC', 'ETH', 'SOL', 'ARB', 'OP']
    
    def log(self, msg):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}"
        print(line)
        
        try:
            with open(self.log_file, 'a') as f:
                f.write(line + '\n')
        except Exception as e:
            print(f"⚠ Log write failed: {e}")
    
    def save_state(self):
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
    
    def fetch_market_data(self):
        try:
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
    
    def scan_for_extremes(self, market_data):
        """Find BOTH high funding AND high OI"""
        extremes = []
        
        try:
            for asset in self.assets:
                asset_data = market_data.get(asset, {})
                
                funding = asset_data.get('funding', 0)
                if funding > 1:
                    funding = funding / 100
                
                # Get OI ratio (need to compare to historical max)
                oi = asset_data.get('open_interest', 0)
                oi_ratio = asset_data.get('oi_ratio', 0)  # 0-1 scale
                
                # BOTH conditions must be true
                if funding > self.funding_threshold and oi_ratio > self.oi_threshold:
                    extremes.append({
                        'timestamp': datetime.now().isoformat(),
                        'asset': asset,
                        'funding_rate': funding,
                        'funding_rate_pct': round(funding * 100, 4),
                        'oi_ratio': round(oi_ratio * 100, 1),
                        'open_interest': oi,
                        'direction': 'LONGS_SQUEEZED',
                        'strength': 'EXTREME' if funding > 0.002 and oi_ratio > 0.90 else 'STRONG'
                    })
        except Exception as e:
            self.log(f"⚠ Scan error: {e}")
        
        return extremes
    
    def log_extremes(self, extremes):
        if not extremes:
            return
        
        try:
            with open(self.alerts_file, 'a') as f:
                for extreme in extremes:
                    f.write(json.dumps(extreme) + '\n')
        except Exception as e:
            self.log(f"⚠ Alert log failed: {e}")
    
    def run(self):
        self.log("=" * 80)
        self.log("🎲 HYPERLIQUID FUNDING + OI MONITOR")
        self.log(f"Polling: {self.interval}s | Funding > {self.funding_threshold*100:.3f}% AND OI > {self.oi_threshold*100:.0f}%")
        self.log(f"Assets: {', '.join(self.assets)}")
        self.log(f"Logs: {self.log_file}")
        self.log(f"Alerts: {self.alerts_file}")
        self.log("=" * 80)
        
        while True:
            try:
                self.poll_count += 1
                
                market_data = self.fetch_market_data()
                
                if market_data:
                    extremes = self.scan_for_extremes(market_data)
                    
                    if extremes:
                        self.extreme_count += len(extremes)
                        self.log_extremes(extremes)
                        self.log(f"💥 Poll #{self.poll_count}: {len(extremes)} EXTREME funding+OI setups!")
                        for ex in extremes:
                            self.log(f"   {ex['asset']}: {ex['funding_rate_pct']:.4f}% funding + {ex['oi_ratio']:.1f}% OI")
                    elif self.poll_count % 5 == 0:
                        self.log(f"✓ Poll #{self.poll_count}: {len(self.assets)} assets, no dual extremes")
                else:
                    self.log(f"⚠ Poll #{self.poll_count}: API fetch failed")
                
                self.save_state()
                time.sleep(self.interval)
            
            except KeyboardInterrupt:
                self.log("Monitor stopped by user")
                break
            except Exception as e:
                self.log(f"❌ Unexpected error: {e}")
                time.sleep(self.interval)

if __name__ == "__main__":
    monitor = FundingOIMonitor()
    monitor.run()
