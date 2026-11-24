#!/bin/bash

# Change to script directory
cd "$(dirname "$0")"

echo "🛑 Stopping LiteChain..."
echo "========================================"

# Stop Docker container
docker-compose down

echo ""
echo "✅ LiteChain stopped"
echo "🔒 Port 8501 freed"
echo ""
echo "You can now safely close this window."
echo ""
read -p "Press any key to exit..."
