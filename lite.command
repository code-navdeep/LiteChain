#!/bin/bash

# Change to script directory
cd "$(dirname "$0")"

echo "🚀 Starting LiteChain..."
echo "======================================"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker Desktop is not running!"
    echo "Please start Docker Desktop and try again."
    read -p "Press any key to exit..."
    exit 1
fi

echo "✅ Docker is running"
echo "🔨 Building and starting LiteChain..."
echo ""

# Start the service
docker-compose up -d --build

# Wait for app to be ready
echo "⏳ Waiting for application to start..."
sleep 6

# Open browser
open http://localhost:8501

echo ""
echo "✅ LiteChain is running!"
echo "📍 Dashboard: http://localhost:8501"
echo ""
echo "🛑 To stop: Run STOP-lite.command"
echo "======================================"
echo ""
read -p "Press any key to exit..."
