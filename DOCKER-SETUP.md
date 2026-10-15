# Docker Setup Guide

## Prerequisites

| OS | Requirements |
|---|---|
| Ubuntu | Docker, make, x11-xserver-utils |
| Windows | Docker Desktop, WSL2 with Ubuntu, make, x11-xserver-utils |
| Mac | Docker Desktop, make |

---

## Ubuntu

### Install Dependencies

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 make x11-xserver-utils

# Add your user to docker group
sudo usermod -aG docker $USER
newgrp docker
```

### Run

```bash
cd /path/to/Persona_V3
make up
```

Chromium window opens directly on your desktop when login is needed.

### Commands

```bash
make up        # Start the app
make down      # Stop the app
make logs      # View logs
make rebuild   # Rebuild after code changes
```

### Access

- Flask app: http://localhost:5000

---

## Windows (WSL2)

### 1. Install Docker Desktop

Download from https://www.docker.com/products/docker-desktop/ and install.

### 2. Install Ubuntu in WSL

Open PowerShell:

```powershell
wsl --install -d Ubuntu
```

Restart your PC after installation.

### 3. Enable Docker WSL Integration

1. Open Docker Desktop
2. Settings → Resources → WSL Integration
3. Toggle on **Ubuntu**
4. Click Apply & Restart

### 4. Setup Project

Open Ubuntu terminal (search "Ubuntu" in Start menu):

```bash
# Install dependencies
sudo apt update && sudo apt install -y make x11-xserver-utils

# Copy project into WSL filesystem (NOT /mnt/c/ — slow)
mkdir -p ~/projects
cp -r /mnt/c/Projects/Persona_V3 ~/projects/Persona_V3
cd ~/projects/Persona_V3
```

### 5. Run

```bash
make up
```

On Windows 11 (WSLg), the Chromium window appears on your Windows desktop when login is needed.

### Verify WSLg is Working

```bash
sudo apt install -y x11-apps
xclock
```

If a clock window appears, GUI forwarding works.

### Commands

```bash
make up        # Start the app
make down      # Stop the app
make logs      # View logs
make rebuild   # Rebuild after code changes
```

### Access

- Flask app: http://localhost:5000

### Important Notes

- Always work inside WSL filesystem (`~/projects/...`), not Windows mount (`/mnt/c/...`) — Docker volumes are extremely slow on `/mnt/c/`
- After changing files on Windows, re-copy into WSL:
  ```bash
  rm -rf ~/projects/Persona_V3
  cp -r /mnt/c/Projects/Persona_V3 ~/projects/Persona_V3
  ```
- Or use VS Code with WSL extension to edit files directly inside WSL:
  ```bash
  code ~/projects/Persona_V3
  ```

---

## Mac

### Install Docker Desktop

```bash
brew install --cask docker
```

Or download from https://www.docker.com/products/docker-desktop/

Open Docker Desktop and wait for it to start.

### Install make (if not installed)

```bash
xcode-select --install
```

### Run (Headless Mode)

```bash
cd /path/to/Persona_V3
make up
```

### Login Mode (VNC)

Mac doesn't support X11 forwarding reliably, so login uses VNC through your browser:

```bash
make login
```

Open http://localhost:6080/vnc.html in your browser — you'll see the Chromium window. Log in, then switch to headless:

```bash
make down
make up
```

### Commands

```bash
make up        # Start headless (after login)
make login     # Start with VNC for browser login
make down      # Stop the app
make logs      # View logs
make rebuild   # Rebuild after code changes
```

### Access

- Flask app: http://localhost:5000
- VNC (login mode only): http://localhost:6080/vnc.html

### Apple Silicon (M1/M2/M3/M4) Note

If you get architecture errors, add `platform: linux/amd64` to your `docker-compose.yml`:

```yaml
services:
  app:
    platform: linux/amd64
    build: .
    # ... rest stays the same
```

### Alternative: Run Ubuntu VM on Mac

For the smoothest experience (no VNC needed), install Ubuntu in a VM:

```bash
brew install --cask utm
```

Download Ubuntu ISO from https://ubuntu.com/download/desktop, create a VM in UTM, install Ubuntu, then follow the Ubuntu instructions above.

---

## File Structure

```
Persona_V3/
├── Dockerfile
├── docker-compose.yml           # Base compose file
├── docker-compose.ubuntu.yml    # Ubuntu/WSL overlay (X11 display)
├── docker-compose.mac.yml       # Mac overlay
├── docker-compose.login.yml     # Mac VNC login overlay
├── entrypoint.sh                # Container startup script
├── makefile                     # Cross-platform run commands
├── req.txt                      # Python dependencies
├── .dockerignore                # Files excluded from Docker build
├── .env                         # Environment variables (DO NOT COMMIT)
├── browser_data/                # Browser profile (DO NOT COMMIT)
├── app.py
├── core.py
├── llm_parser.py
├── ranker.py
├── session_manager.py
└── templates/
```

---

## Security Notes

- `browser_data/` contains session cookies — treat it like a password file
  ```bash
  chmod 700 ./browser_data
  ```
- Add to `.gitignore`:
  ```
  browser_data/
  .env
  ```
- VNC (Mac login mode) binds to `127.0.0.1` only — not accessible from the network
- Container runs as non-root user (`appuser`)
- All Linux capabilities are dropped (`cap_drop: ALL`)

---

## Troubleshooting

### Container crashes immediately
```bash
docker compose logs -f
```

### Chromium crashes with no error
Increase shared memory:
```yaml
# docker-compose.yml
shm_size: '512m'  # increase from 256m
```

### "Permission denied" on browser_data
```bash
sudo chown -R $USER:$USER ./browser_data
```

### Port 5000 already in use
```bash
# Find what's using it
lsof -i :5000

# Or change the port in docker-compose.yml
ports:
  - "8080:5000"  # access at localhost:8080 instead
```

### WSL: Docker command not found
Open Docker Desktop → Settings → Resources → WSL Integration → enable your Ubuntu distro → Apply & Restart

### Mac: xhost unable to open display
Don't use X11 on Mac. Use `make login` instead (VNC approach).

### Rebuild from scratch
```bash
docker compose build --no-cache
docker compose up -d
```
