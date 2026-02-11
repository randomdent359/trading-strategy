#!/usr/bin/env python3
"""
Polymarket Strength-Filtered Monitor
Only trades extreme consensus (>80%), skips moderate (72-80%)

Theory: The strongest extremes are the most wrong.
Win rate target: 55-58%
"""

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

class StrengthFilteredMonitor:
    def __init__(self):
        self.pm_api = "https://gamma-api.polymarket.com"
        
        self.base_dir = Path.home() / "trading" / "polymarket"
        self.logs_dir = self.base_dir / "logs"
        self.data_dir = self.base_dir / "data"
        
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_file = self.logs_dir / "strength-filtered-monitor.log"
        self.alerts_file = self.data_dir / "strength-filtered-extremes.jsonl"
        self.state_file = self.data_dir / "strength-filtered-state.json"
        
        self.interval = 30
        self.min_consensus = 0.80  # ONLY trade >80% (skip 72-80%)
        
        self.poll_count = 0
        self.extreme_count = 0
    
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
    
    def fetch_markets(self):
        try:
            result = subprocess.run([
                'curl', '-s', '--max-time', '5',
                f'{self.pm_api}/series'
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                return []
            
            data = json.loads(result.stdout)
            return data if isinstance(data, list) else []
        except Exception as e:
            self.log(f"❌ API fetch error: {e}")
            return []
    
    def scan_for_extremes(self, markets):
        """Only find STRONG extremes (>80%)"""
        extremes = []
        
        try:
            for market in markets:
                title = market.get('title', '').upper()
                if not any(x in title for x in ['UP', 'DOWN', 'ETH', 'BTC', 'SOL']):
                    continue
                
                if not market.get('active'):
                    continue
                
                prices_raw = market.get('outcomePrices', '[]')
                if isinstance(prices_raw, str):
                    prices = json.loads(prices_raw)
                else:
                    prices = prices_raw
                
                outcomes_raw = market.get('outcomes', '[]')
                if isinstance(outcomes_raw, str):
                    outcomes = json.loads(outcomes_raw)
                else:
                    outcomes = outcomes_raw
                
                if not prices or len(prices) < 2:
                    continue
                
                for i, price_str in enumerate(prices):
                    try:
                        prob = float(price_str)
                        
                        # ONLY trade >80% (skip 72-80%)
                        if prob > self.min_consensus or prob < (1 - self.min_consensus):
                            consensus_outcome = outcomes[i] if i < len(outcomes) else "?"
                            contrarian_outcome = outcomes[1-i] if i < len(outcomes) else None
                            
                            extremes.append({
                                'timestamp': datetime.now().isoformat(),
                                'market_title': market.get('title', 'unknown'),
                                'market_id': market.get('id'),
                                'consensus_outcome': consensus_outcome,
                                'consensus_probability': round(prob * 100, 1),
                                'contrarian_outcome': contrarian_outcome,
                                'contrarian_probability': round((1 - prob) * 100, 1),
                                'strength': 'EXTREME' if prob > 0.85 else 'STRONG'
                            })
                    except (ValueError, IndexError):
                        pass
        except Exception:
            pass
        
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
        self.log("🎲 POLYMARKET STRENGTH-FILTERED MONITOR")
        self.log(f"Polling: {self.interval}s | Min consensus: {self.min_consensus*100:.0f}% (STRONG ONLY)")
        self.log(f"Logs: {self.log_file}")
        self.log(f"Alerts: {self.alerts_file}")
        self.log("=" * 80)
        
        while True:
            try:
                self.poll_count += 1
                markets = self.fetch_markets()
                
                if markets:
                    extremes = self.scan_for_extremes(markets)
                    
                    if extremes:
                        self.extreme_count += len(extremes)
                        self.log_extremes(extremes)
                        self.log(f"💪 Poll #{self.poll_count}: {len(markets)} markets | {len(extremes)} STRONG extremes (cumulative: {self.extreme_count})")
                    else:
                        if self.poll_count % 10 == 0:
                            self.log(f"✓ Poll #{self.poll_count}: {len(markets)} markets, no >80% extremes")
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
    monitor = StrengthFilteredMonitor()
    monitor.run()
