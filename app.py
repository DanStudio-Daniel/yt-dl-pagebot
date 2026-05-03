import os
import requests
import yt_dlp
from flask import Flask, request

app = Flask(__name__)

# --- CONFIGURATION ---
PAGE_ACCESS_TOKEN = os.environ.get('PAGE_ACCESS_TOKEN')
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')

# --- HELPERS ---
def send_message(recipient_id, text):
    url = f"https://graph.facebook.com/v17.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    requests.post(url, json=payload)

def process_and_send(recipient_id, url, mode):
    ext = 'mp3' if mode == 'mp3' else 'mp4'
    filename = f"{recipient_id}.{ext}"
    
    ydl_opts = {
        'format': 'bestaudio/best' if mode == 'mp3' else 'best[ext=mp4]/best',
        'outtmpl': filename,
        'max_filesize': 25000000, # 25MB Limit for FB
    }
    
    if mode == 'mp3':
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Upload to Facebook
        fb_url = f"https://graph.facebook.com/v17.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
        with open(filename, 'rb') as f:
            files = {
                'recipient': (None, '{"id":"' + recipient_id + '"}'),
                'message': (None, '{"attachment":{"type":"file", "payload":{}}}'),
                'filedata': (filename, f, 'audio/mpeg' if mode == 'mp3' else 'video/mp4')
            }
            requests.post(fb_url, files=files)
    except Exception as e:
        send_message(recipient_id, f"Error: File might be over 25MB or link is dead.")
    finally:
        if os.path.exists(filename):
            os.remove(filename)

# --- ROUTES ---

@app.route('/')
def home():
    return "<h1>bot running</h1>", 200

@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verification failed", 403

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data.get("object") == "page":
        for entry in data["entry"]:
            for event in entry.get("messaging", []):
                sender_id = event["sender"]["id"]
                if event.get("message"):
                    text = event["message"].get("text", "").lower()
                    
                    if "youtube.com" in text or "youtu.be" in text:
                        # Store the link in a very simple way for the next message
                        # For a real bot, you'd use a small cache here
                        send_message(sender_id, "Got link! Type 'mp3' or 'mp4' to download.")
                        os.environ[f"last_url_{sender_id}"] = text
                    
                    elif text in ['mp3', 'mp4']:
                        last_url = os.environ.get(f"last_url_{sender_id}")
                        if last_url:
                            send_message(sender_id, f"Processing {text}...")
                            process_and_send(sender_id, last_url, text)
                        else:
                            send_message(sender_id, "Please send a YouTube link first.")
                            
    return "EVENT_RECEIVED", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
