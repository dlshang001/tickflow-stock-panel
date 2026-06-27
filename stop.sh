#!/bin/bash
# TickFlow Stock Panel 一键停止脚本

stop_port() {
    local PORT=$1
    local NAME=$2
    local PID=$(lsof -i :$PORT | grep LISTEN | awk '{print $2}')
    if [ -z "$PID" ]; then
        echo "❌ 没有找到 $NAME ($PORT 端口) 的进程"
    else
        echo "🔍 找到 $NAME 进程 PID: $PID，正在停止..."
        kill -9 $PID
        echo "✅ $NAME ($PID) 已停止，端口 $PORT 已释放"
    fi
}

# 停止前端 (3011)
stop_port 3011 "前端 (Vite)"

# 停止后端 (3018)
stop_port 3018 "后端 (FastAPI)"
