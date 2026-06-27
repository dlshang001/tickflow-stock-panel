#!/bin/bash
# TickFlow Stock Panel 一键重启脚本（先停止，再后台启动）

# ----- 停止 -----
stop_port() {
    local PORT=$1
    local NAME=$2
    local PID=$(lsof -i :$PORT 2>/dev/null | grep LISTEN | awk '{print $2}')
    if [ -z "$PID" ]; then
        echo "❌ 没有找到 $NAME ($PORT 端口) 的进程"
    else
        echo "🔍 找到 $NAME 进程 PID: $PID，正在停止..."
        kill -9 $PID
        echo "✅ $NAME ($PID) 已停止，端口 $PORT 已释放"
    fi
}

echo "===== 停止旧服务 ====="
stop_port 3011 "前端 (Vite)"
stop_port 3018 "后端 (FastAPI)"
echo ""

# ----- 启动 -----

# 1. 进入项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT" || exit 1

echo "===== 启动新服务 ====="

# 2. 后台启动后端 (FastAPI)
cd "$PROJECT_ROOT/backend" || exit 1
nohup uv run uvicorn app.main:app --host 0.0.0.0 --port 3018 > "$PROJECT_ROOT/backend.log" 2>&1 &
BACKEND_PID=$!
echo "✅ 后端已启动，进程号：$BACKEND_PID  → http://localhost:3018"

# 3. 后台启动前端 (Vite)
cd "$PROJECT_ROOT/frontend" || exit 1
nohup pnpm dev --host 0.0.0.0 --port 3011 > "$PROJECT_ROOT/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "✅ 前端已启动，进程号：$FRONTEND_PID  → http://localhost:3011"

echo ""
echo "===== 信息 ====="
echo "后端日志：$PROJECT_ROOT/backend.log"
echo "前端日志：$PROJECT_ROOT/frontend.log"
echo "停止后端：kill $BACKEND_PID"
echo "停止前端：kill $FRONTEND_PID"
echo "查看后端日志：tail -f $PROJECT_ROOT/backend.log"
echo "查看前端日志：tail -f $PROJECT_ROOT/frontend.log"
