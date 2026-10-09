# CampusMate — Production HTTPS Deployment Guide

This guide describes how to host the CampusMate MCP Server standalone over HTTPS for compliant external MCP clients (such as Amazon Alexa+ skills, Claude Desktop, or MCP Inspector).

---

## 1. Architecture for HTTPS Hosting

```text
External Client (Alexa+ / Claude) 
           │
           ▼  HTTPS (Port 443)
┌──────────────────────────────────────────┐
│ Reverse Proxy (Nginx / Caddy with TLS)   │
└──────────────────┬───────────────────────┘
                   │  HTTP (Port 8000)
                   ▼
┌──────────────────────────────────────────┐
│ CampusMate MCP Server (Streamable HTTP)  │
│ Endpoint: /mcp                           │
│ Health:   /health                        │
└──────────────────────────────────────────┘
```

---

## 2. Nginx Configuration Template

Create `/etc/nginx/sites-available/campusmate`:

```nginx
server {
    server_name mcp.campusmate.edu;

    location /mcp {
        proxy_pass http://127.0.0.1:8000/mcp;
        proxy_http_version 1.1;

        # Critical for Streamable HTTP & SSE streaming
        proxy_set_header Connection '';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Disable buffering for streaming responses
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        chunked_transfer_encoding on;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        proxy_set_header Host $host;
    }

    listen 443 ssl http2;
    ssl_certificate /etc/letsencrypt/live/mcp.campusmate.edu/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.campusmate.edu/privkey.pem;
}
```

---

## 3. Caddy Alternative Configuration

If using Caddy, create `/etc/caddy/Caddyfile`:

```caddy
mcp.campusmate.edu {
    reverse_proxy /mcp* http://127.0.0.1:8000 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
        flush_interval -1
    }

    reverse_proxy /health http://127.0.0.1:8000
}
```

---

## 4. Systemd Service Setup

Create `/etc/systemd/system/campusmate-mcp.service`:

```ini
[Unit]
Description=CampusMate Standalone MCP Server
After=network.target

[Service]
Type=simple
User=campusmate
WorkingDirectory=/opt/campusmate
ExecStart=/opt/campusmate/.venv/bin/python -m campusmate.server.app.main --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
Environment=CAMPUSMATE_TZ=UTC
Environment=DATABASE_URL=sqlite:////opt/campusmate/campusmate.db

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now campusmate-mcp
```

Verify with:
```bash
curl https://mcp.campusmate.edu/health
```
