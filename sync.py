import os
import sqlite3
import hashlib
import requests
import concurrent.futures
from requests_oauthlib import OAuth1

# Configuration pulled from Environment Variables
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
ACCESS_SECRET = os.getenv('ACCESS_SECRET')
NICKNAME = os.getenv('NICKNAME')
DATA_DIR = "/data"
BASE_URL = "https://api.smugmug.com/api/v2"

class SmugMugSync:
    def __init__(self):
        self.auth = OAuth1(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET)
        self.db_path = os.path.join(DATA_DIR, "sync_state.db")
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS photos 
                           (image_key TEXT PRIMARY KEY, md5 TEXT, path TEXT)''')

    def get_json(self, url):
        headers = {'Accept': 'application/json'}
        r = requests.get(url, auth=self.auth, headers=headers)
        return r.json().get('Response', {})

    def get_md5(self, filepath):
        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def download_image(self, image_data, album_path):
        ikey = image_data['ImageKey']
        fname = image_data['FileName']
        url = image_data['ArchivedUri']
        remote_md5 = image_data['ArchivedMD5']
        local_path = os.path.join(album_path, fname)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT md5 FROM photos WHERE image_key=?", (ikey,)).fetchone()
            if row and os.path.exists(local_path):
                if row[0] == remote_md5:
                    return

        os.makedirs(album_path, exist_ok=True)
        print(f"Downloading: {fname}")
        try:
            r = requests.get(url, stream=True)
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            local_md5 = self.get_md5(local_path)
            if local_md5 == remote_md5:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("INSERT OR REPLACE INTO photos VALUES (?, ?, ?)", (ikey, local_md5, local_path))
        except Exception as e:
            print(f"Error downloading {fname}: {e}")

    def process_album(self, album_url, path):
        album_data = self.get_json(f"{BASE_URL}{album_url}!images")
        images = album_data.get('AlbumImage', [])
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(self.download_image, img, path) for img in images]
            concurrent.futures.wait(futures)

    def walk_nodes(self, node_url, current_path):
        data = self.get_json(f"{BASE_URL}{node_url}!children")
        for node in data.get('Node', []):
            name = node['Name'].replace('/', '-')
            new_path = os.path.join(current_path, name)
            if node['Type'] == 'Album':
                self.process_album(node['Uri'], new_path)
            elif node['Type'] == 'Folder':
                self.walk_nodes(node['Uri'], new_path)

    def run(self):
        user_root = self.get_json(f"{BASE_URL}/user/{NICKNAME}!node")
        if 'Node' in user_root:
            self.walk_nodes(user_root['Node']['Uri'], DATA_DIR)
        else:
            print("Error: Could not find user root. Check your NICKNAME and API keys.")

if __name__ == "__main__":
    SmugMugSync().run()
