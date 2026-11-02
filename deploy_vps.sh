#!/bin/bash
set -e

echo "======================================================"
echo "🚀 AutoFilterBot & Fast Streaming Engine - VPS Installer"
echo "======================================================"

# 1. Update and install system dependencies
echo "📦 Installing system dependencies..."
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip python3-venv git curl ufw net-tools

# 2. Setup Virtual Environment
echo "🐍 Setting up Python Virtual Environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Detect Public IP & Safe Free Port
PUBLIC_IP=$(curl -s -4 ifconfig.me || curl -s -4 icanhazip.com || hostname -I | awk '{print $1}')
echo "🌐 Detected Public IPv4: $PUBLIC_IP"

# Check if port 8080 is busy
PORT=8080
if ss -tuln | grep -q ":8080 " || netstat -tuln 2>/dev/null | grep -q ":8080 "; then
    echo "⚠️ Port 8080 is already in use by another service on this VPS!"
    PORT=8088
    echo "⚡ Automatically switching AutoFilterBot to Port: $PORT"
else
    echo "✅ Port 8080 is free!"
fi

# 4. Configure .env with Port and Stream URL
if [ -f ".env" ]; then
    # Update or add PORT
    if grep -q "^PORT=" .env; then
        sed -i "s/^PORT=.*/PORT=$PORT/" .env
    else
        echo "PORT=$PORT" >> .env
    fi

    # Update or add STREAM_URL
    if grep -q "^STREAM_URL=" .env; then
        sed -i "s|^STREAM_URL=.*|STREAM_URL=http://$PUBLIC_IP:$PORT|" .env
    else
        echo "STREAM_URL=http://$PUBLIC_IP:$PORT" >> .env
    fi
    echo "✅ Configured .env with PORT=$PORT and STREAM_URL=http://$PUBLIC_IP:$PORT"
fi

# 5. Open Port in Firewall (UFW)
if command -v ufw >/dev/null 2>&1; then
    echo "🛡️ Configuring Firewall (Port $PORT)..."
    sudo ufw allow $PORT/tcp || true
fi

# 6. Create Systemd Service for 24/7 background uptime
APP_DIR=$(pwd)
SERVICE_FILE="/etc/systemd/system/autofilterbot.service"

echo "⚙️ Creating systemd service: autofilterbot.service..."
sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=AutoFilterBot and Streaming Server
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable autofilterbot
sudo systemctl restart autofilterbot

echo ""
echo "======================================================"
echo "🎉 DEPLOYMENT COMPLETE! BOT IS LIVE IN BACKGROUND!"
echo "======================================================"
echo "📊 Check status:   sudo systemctl status autofilterbot"
echo "📜 View live logs: sudo journalctl -u autofilterbot -f"
echo "🌐 Streaming URL:  http://$PUBLIC_IP:$PORT"
echo "======================================================"
