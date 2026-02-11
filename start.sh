#!/bin/bash
# 1. 환경 변수 강제 로드
source /etc/profile
source ~/.bash_profile

# 2. 경로 설정
APP_PATH="/opt/h-cmp"
cd $APP_PATH

# 3. uvicorn 절대 경로 확인 (which uvicorn으로 확인한 경로를 넣으세요)
# 보통 /usr/local/bin/uvicorn 입니다.
UVICORN_BIN=$(which uvicorn)

# 4. 기존 프로세스 종료
pkill -f uvicorn || true

# 5. 백그라운드 실행 (입출력 완전 차단)
nohup $UVICORN_BIN main:app --host 0.0.0.0 --port 8000 </dev/null > uvicorn.log 2>&1 &

# 6. 실행 확인 (약간의 대기 후)
sleep 2
if ps -ef | grep -v grep | grep uvicorn > /dev/null; then
    echo "--- Uvicorn Started Successfully ---"
    exit 0
else
    echo "--- Uvicorn Failed to Start ---"
    cat uvicorn.log
    exit 1
fi