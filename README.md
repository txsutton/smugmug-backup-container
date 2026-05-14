# 📸 SmugMug Professional Docker Sync

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)

A high-performance, hash-verified backup solution for SmugMug. Optimized for **Asustor, Synology, and Unraid** NAS environments.

---

### 🌟 Key Features

| Feature | Description |
| :--- | :--- |
| **MD5 Verification** | Detects corrupted or partial downloads and auto-repairs them. |
| **SQLite Engine** | Persistent state tracking for near-instant resume and sync. |
| **Docker-Native** | Headless execution—perfect for scheduled tasks or background services. |
| **Secure by Design** | Zero-footprint credentials; uses Environment Variables only. |
| **Smart Mirroring** | Recreates your SmugMug folder/album hierarchy locally. |

---

### 🔑 Getting Your Credentials

You need **API Keys** (App ID) and **User Tokens** (Your Permission) to run this tool.

#### 1. Create your SmugMug App
*   Log into the [SmugMug API Dashboard](https://api.smugmug.com/api/v2/apps).
*   Register a new app and copy your **API Key** and **API Secret**.

#### 2. The OAuth Dance (Generate User Tokens)
Use the included `authenticate.py` utility to link your account.

```bash
# 1. Install requirements
pip install rauth

# 2. Run the generator
python authenticate.py
```

#### The Authentication Process:
1. Enter Keys: Input your API Key and Secret when prompted by the script.
2. Authorize: Open the generated URL in your browser and click Authorize.
3. Enter PIN: Paste the 6-digit PIN provided by SmugMug back into your terminal.
4. Save Tokens: Copy the USER_TOKEN and USER_SECRET provided at the end. Keep these secret!

---

### 🔑 Setup & Security

#### Create your .env File
To keep your credentials secure, create a file named `.env` in your project root (same folder as the docker-compose file). **Never commit this file to GitHub.**

Add the following to the file:
```text
API_KEY=your_key_here
API_SECRET=your_secret_here
ACCESS_TOKEN=your_token_here
ACCESS_SECRET=your_token_secret_here
NICKNAME=your_smugmug_nickname
```

### 🚀 Deployment

#### 1. Build the Image
Clone this repo to your server and build your private image:
```bash
docker build -t smugmug-sync-pro:latest .
```
#### 2. Stack Configuration (Portainer / Docker Compose)
Paste this into your Portainer Stack or docker-compose.yaml. Replacing Volumes to point to where you wish the files to be copied to
```yaml
version: '3.8'
services:
  smugmug-sync:
    image: smugmug-sync-pro:latest
    container_name: smugmug_backup
    read_only: true  # <--- Locks the container filesystem
    tmpfs:
      - /tmp         # <--- Gives Python a place for temporary files
    env_file: .env
    environment:
      - API_KEY=${API_KEY}
      - API_SECRET=${API_SECRET}
      - ACCESS_TOKEN=${ACCESS_TOKEN}
      - ACCESS_SECRET=${ACCESS_SECRET}
      - NICKNAME=${NICKNAME}
      - PYTHONDONTWRITEBYTECODE=1 # <--- Prevents writing .pyc files
    volumes:
      - /volume2/Photos/smugmug-backup:/data
    restart: unless-stopped
```
---

### 📂 Project Structure

* sync.py - The Engine: Core synchronization and hash verification logic.
* authenticate.py - The Keymaker: One-time utility for OAuth tokens.
* Dockerfile - The Blueprint: Instructions for the slim Python environment.
* requirements.txt - The Logic: Python library dependencies.
* stack-docker-compose.yaml - The Recipe: Deployment template for Portainer.

---

### ❤️ Credits & Inspiration
This project was inspired by the [smugmug-bulk-downloader](https://github.com/dannoll/smugmug-bulk-downloader) by dannoll. 

While this version is a ground-up rewrite for Docker-native workflows (introducing SQLite and MD5 verification), the API interaction logic was guided by the original repository's excellent foundation.

---

### License
Distributed under the MIT License.
