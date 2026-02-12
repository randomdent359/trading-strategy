#!/usr/bin/env python3
"""Test script for Trading Dashboard API endpoints."""

import httpx
import asyncio
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"


async def test_endpoints():
    """Test all API endpoints."""
    async with httpx.AsyncClient() as client:
        print("Testing Trading Dashboard API...\n")

        # 1. Health check
        print("1. Testing /api/health")
        try:
            response = await client.get(f"{BASE_URL}/api/health")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {json.dumps(response.json(), indent=2)}\n")
        except Exception as e:
            print(f"   Error: {e}\n")

        # 2. List strategies
        print("2. Testing /api/strategies")
        try:
            response = await client.get(f"{BASE_URL}/api/strategies")
            print(f"   Status: {response.status_code}")
            data = response.json()
            print(f"   Found {len(data['strategies'])} strategies")
            for strategy in data['strategies'][:3]:  # Show first 3
                print(f"   - {strategy['name']}: {strategy['totalTrades']} trades, "
                      f"P&L: ${strategy['totalPnl']:.2f}\n")
        except Exception as e:
            print(f"   Error: {e}\n")

        # 3. Get signals for a strategy
        print("3. Testing /api/strategies/{name}/signals")
        try:
            response = await client.get(f"{BASE_URL}/api/strategies/contrarian_pure/signals?limit=5")
            print(f"   Status: {response.status_code}")
            data = response.json()
            print(f"   Total signals: {data['total']}")
            print(f"   Showing {len(data['signals'])} most recent\n")
        except Exception as e:
            print(f"   Error: {e}\n")

        # 4. Get trades for a strategy
        print("4. Testing /api/strategies/{name}/trades")
        try:
            response = await client.get(f"{BASE_URL}/api/strategies/contrarian_pure/trades?limit=5")
            print(f"   Status: {response.status_code}")
            data = response.json()
            print(f"   Total trades: {data['total']}")
            print(f"   Showing {len(data['trades'])} most recent\n")
        except Exception as e:
            print(f"   Error: {e}\n")

        # 5. Get equity curve
        print("5. Testing /api/equity-curve")
        try:
            response = await client.get(f"{BASE_URL}/api/equity-curve")
            print(f"   Status: {response.status_code}")
            data = response.json()
            print(f"   Data points: {len(data['data'])}")
            if data['data']:
                latest = data['data'][-1]
                print(f"   Latest equity: ${latest['totalEquity']:.2f}\n")
        except Exception as e:
            print(f"   Error: {e}\n")

        # 6. Get open positions
        print("6. Testing /api/positions/open")
        try:
            response = await client.get(f"{BASE_URL}/api/positions/open")
            print(f"   Status: {response.status_code}")
            data = response.json()
            print(f"   Open positions: {len(data['positions'])}\n")
        except Exception as e:
            print(f"   Error: {e}\n")

        # 7. Get asset performance
        print("7. Testing /api/assets/{asset}/performance")
        try:
            response = await client.get(f"{BASE_URL}/api/assets/BTC/performance")
            print(f"   Status: {response.status_code}")
            data = response.json()
            print(f"   BTC total trades: {data['totalTrades']}")
            print(f"   BTC total P&L: ${data['totalPnl']:.2f}\n")
        except Exception as e:
            print(f"   Error: {e}\n")

        # 8. Get portfolio summary
        print("8. Testing /api/summary")
        try:
            response = await client.get(f"{BASE_URL}/api/summary")
            print(f"   Status: {response.status_code}")
            data = response.json()
            print(f"   Total equity: ${data['totalEquity']:.2f}")
            print(f"   Sharpe ratio: {data['sharpeRatio']}")
            print(f"   Max drawdown: {data['maxDrawdown']:.2f}%\n")
        except Exception as e:
            print(f"   Error: {e}\n")


if __name__ == "__main__":
    asyncio.run(test_endpoints())