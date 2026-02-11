import requests
import json
import sys
import time

PROMETHEUS_URL = "http://localhost:19090/api/v1/query"

def queries():
    # 1. CPU Query
    print("\n[Test 1] Fetching CPU Usage...")
    # cpu_query = '100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)'
    cpu_query = 'node_cpu_seconds_total{mode="idle"}' 
    
    try:
        response = requests.get(PROMETHEUS_URL, params={'query': cpu_query}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            results = data.get('data', {}).get('result', [])
            print(f"[OK] Raw Data Count: {len(results)}")
            for res in results[:2]: # 2 items
                # instance label might be 'IP:9100' or just 'hostname'
                print(f"  - Instance: {res['metric'].get('instance')}")
                print(f"  - Value: {res['value']}")
        else:
            print(f"[ERROR] HTTP Status: {response.text}")
    except Exception as e:
        print(f"[ERROR] Connection Error: {e}")

    # 2. Check Instance Mapping
    print("\n[Test 2] Checking 'up' metric for Instance Names")
    try:
        response = requests.get(PROMETHEUS_URL, params={'query': 'up'}, timeout=5)
        results = response.json().get('data', {}).get('result', [])
        print("[OK] Active Instances:")
        for res in results:
             print(f"  - {res['metric'].get('instance')} (Job: {res['metric'].get('job')})")
    except Exception as e:
        print(f"[ERROR] Error: {e}")

queries()
