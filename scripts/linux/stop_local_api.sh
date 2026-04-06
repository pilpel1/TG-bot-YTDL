#!/bin/bash

echo "========================================"
echo "  Stopping Local Bot API Server"
echo "========================================"
echo

echo "Stopping Docker container..."
docker stop telegram-bot-api 2>/dev/null
docker rm telegram-bot-api 2>/dev/null

if [ $? -eq 0 ]; then
    echo "✓ Local Bot API Server stopped successfully"
else
    echo "⚠ Container might not be running or already stopped"
fi

echo
echo "========================================"
echo "  🛑 Server Stopped"
echo "========================================"
echo
read -p "Press any key to continue..."
