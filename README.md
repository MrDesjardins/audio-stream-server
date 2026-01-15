
# Install Dependencies

```sh
sudo apt update
sudo apt install -y yt-dlp ffmpeg icecast2

sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
sudo chmod a+rx /usr/local/bin/yt-dlp

sudo mv /usr/local/bin/yt-dlp /usr/bin/yt-dlp
sudo chmod a+rx /usr/bin/yt-dlp
export PATH="/usr/local/bin:$PATH"

yt-dlp --version

uv sync
```

# Configure

```
sudo nano /etc/icecast2/icecast.xml
```

Change: 
```
<hostname>mini-pc</hostname>
<location>Home</location>
<admin>patrick@localhost</admin>
<listen-socket>
   <port>8000</port>
   <bind-address>0.0.0.0</bind-address> <!-- listen on all IPs -->
</listen-socket>
```

# Server configuration

```sh
sudo ufw allow 8000/tcp
sudo ufw allow 8001/tcp
sudo ufw reload
sudo ufw status
```

# Run

```sh
FASTAPI_HOST=127.0.0.1 FASTAPI_API_PORT=8000 uv run main.py

FASTAPI_HOST=10.0.0.181 FASTAPI_API_PORT=8000 uv run main.py
```