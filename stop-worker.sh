#!/bin/bash
# Stop Celery worker

echo "🛑 Stopping Celery worker..."

# Try graceful shutdown first
if [ -f logs/celery_worker.pid ]; then
    PID=$(cat logs/celery_worker.pid 2>/dev/null)
    if [ -n "$PID" ]; then
        echo "Stopping worker with PID: $PID"
        kill $PID 2>/dev/null
        sleep 2

        # Check if still running
        if ps -p $PID > /dev/null 2>&1; then
            echo "Force killing worker..."
            kill -9 $PID 2>/dev/null
        fi
    fi
fi

# Kill any remaining celery worker processes
pkill -f "celery.*worker" 2>/dev/null
sleep 1

# Force kill if still running
pkill -9 -f "celery.*worker" 2>/dev/null

# Check if stopped
if ps aux | grep -v grep | grep "celery.*worker" > /dev/null; then
    echo "❌ Some worker processes may still be running:"
    ps aux | grep -v grep | grep "celery.*worker"
else
    echo "✅ Celery worker stopped successfully"
fi
