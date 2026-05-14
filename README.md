# SmugMug Docker Sync

A robust, hash-verified backup solution for SmugMug, optimized for Docker and NAS environments (Asustor, Synology, Unraid).

## 🌟 Key Features
- **MD5 Hash Verification:** Automatically detects corrupted or partial downloads and re-fetches them.
- **SQLite Persistence:** Tracks sync state in a local database (`sync_state.db`) for lightning-fast subsequent runs.
- **Docker-Native:** Designed to run as a headless service without manual interaction.
- **Secure Architecture:** Uses environment variables for secrets; no API keys are stored in the codebase.
- **Recursive Mirroring:** Automatically maps your SmugMug folder/album structure to your local drive.

---

## 🔑 Getting Your Credentials

You need two sets of keys to use this tool: **API Keys** and **User Tokens**.

### 1. Create your SmugMug App
1. Log into the [SmugMug API Dashboard](https://api.smugmug.com/api/v2/apps).
2. Create a new app and note your **API Key** and **API Secret**.

### 2. Generate User Tokens (OAuth 1.0a)
Use the included `authenticate.py` script to grant this tool permission to access your account.

1. **Install dependencies:** 
   ```bash
   pip install rauth
Run the utility:

Bash
python authenticate.py
The OAuth Dance:

Input your API Key and Secret when prompted.

Copy the provided URL into your browser and click Authorize.

Copy the 6-digit PIN and paste it back into the script terminal.

Save Results: The script will output your USER_TOKEN and USER_SECRET. You will need these for the Docker setup.

🚀 Deployment
1. Build the Image
Clone this repo to your server and build the image:

Bash
docker build -t your-username/smugmug-sync:latest .
2. Stack Configuration (Portainer / Docker Compose)
Use this configuration to deploy the sync engine. Replace the placeholders with your actual keys.

YAML
version: '3.8'
services:
  smugmug-sync:
    image: your-username/smugmug-sync:latest
    container_name: smugmug_backup
    environment:
      - API_KEY=your_api_key_here
      - API_SECRET=your_api_secret_here
      - ACCESS_TOKEN=your_user_token_here
      - ACCESS_SECRET=your_user_secret_here
      - NICKNAME=your_smugmug_nickname
    volumes:
      - /volume2/Photos/smugmug-backup:/data
    restart: unless-stopped
🛠 Project Structure
sync.py: The core synchronization engine.

authenticate.py: One-time use utility for generating OAuth tokens.

Dockerfile: Instructions to build the lightweight Python image.

requirements.txt: Python library dependencies.

stack-docker-compose.yaml: Template for Portainer deployment.

❤️ Credits & Inspiration
This project was inspired by the smugmug-bulk-downloader created by dannoll.

While this version has been completely re-architected for Docker-native workflows (using SQLite state tracking and MD5 verification), the logic for interacting with the SmugMug API was built upon the foundations laid by the original repository.

⚖️ License
This project is licensed under the MIT License - see the LICENSE file for details.
