import requests
import sys

# 터널링된 Prometheus 주소 (가이드했던 19090 포트 가정)
PROMETHEUS_URL = "http://localhost:19090/api/v1/query"

print(f"[INFO] Connecting to Prometheus via SSH tunnel: {PROMETHEUS_URL}")

try:
    # 1. 간단한 쿼리 ('up')로 연결 테스트
    response = requests.get(PROMETHEUS_URL, params={'query': 'up'}, timeout=5)
    
    if response.status_code == 200:
        data = response.json()
        status = data.get('status')
        if status == 'success':
            results = data.get('data', {}).get('result', [])
            print(f"[SUCCESS] Connection Successful!")
            print(f"   Status: {status}")
            print(f"   Active Targets: {len(results)}")
            
            # 상위 3개 타겟만 출력
            for i, res in enumerate(results[:3]):
                instance = res['metric'].get('instance', 'unknown')
                job = res['metric'].get('job', 'unknown')
                print(f"   - Target {i+1}: {instance} ({job})")
        else:
             print(f"[WARNING] Connected, but status is '{status}': {data}")
    else:
        print(f"[ERROR] HTTP Status Code: {response.status_code}")
        print(f"   Response: {response.text[:200]}")

except requests.exceptions.ConnectionError:
    print(f"[ERROR] Connection Refused. Is the SSH tunnel running on port 19090?")
    print("      Check command: ssh -L 19090:<PROMETHEUS_IP>:9090 root@...")
except Exception as e:
    print(f"[ERROR] Unexpected error: {e}")
