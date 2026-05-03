import os
import requests
import yt_dlp
from flask import Flask, request
from cachetools import TTLCache

app = Flask(__name__)

# Cache stores user links for 10 minutes
link_cache = TTLCache(maxsize=100, ttl=600)

# Environment Variables
PAGE_ACCESS_TOKEN = os.environ.get('PAGE_ACCESS_TOKEN')
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')

def send_action(recipient_id, action):
    """
    Actions: 
    'mark_seen' - Removes the 'unread' notification
    'typing_on' - Shows the typing dots
    'typing_off' - Hides the typing dots
    """
    url = f"https://graph.facebook.com/v17.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "sender_action": action
    }
    requests.post(url, json=payload)

def send_message(recipient_id, text):
    """Sends a standard text response."""
    url = f"https://graph.facebook.com/v17.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    requests.post(url, json=payload)

def process_and_send(recipient_id, url, mode):
    """Downloads and uploads the file."""
    ext = 'mp3' if mode == 'mp3' else 'mp4'
    filename = f"dl_{recipient_id}.{ext}"
    
    # Start typing indicator for the long download process
    send_action(recipient_id, "typing_on")
    
    ydl_opts = {
        'format': 'bestaudio/best' if mode == 'mp3' else 'best[ext=mp4]/best',
        'outtmpl': filename,
        'max_filesize': 25000000, 
        'quiet': True
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
        
        fb_url = f"https://graph.facebook.com/v17.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
        with open(filename, 'rb') as f:
            files = {
                'recipient': (None, '{"id":"' + recipient_id + '"}'),
                'message': (None, '{"attachment":{"type":"file", "payload":{}}}'),
                'filedata': (filename, f, 'audio/mpeg' if mode == 'mp3' else 'video/mp4')
            }
            requests.post(fb_url, files=files)
        send_message(recipient_id, "✅ Done! Your file is ready.")
    except Exception as e:
        send_message(recipient_id, "⚠️ Error: File too large (>25MB) or restricted link.")
    finally:
        send_action(recipient_id, "typing_off")
        if os.path.exists(filename):
            os.remove(filename)

@app.route('/')
def home():
    return "<h1>bot running</h1>", 200

@app.route('/webhook', methods=['GET'])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Unauthorized", 403

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data.get("object") == "page":
        for entry in data["entry"]:
            for event in entry.get("messaging", []):
                sender_id = event["sender"]["id"]
                
                # --- AUTO SEEN ---
                send_action(sender_id, "mark_seen")

                if "message" in event and "text" in event["message"]:
                    msg_text = event["message"]["text"].lower().strip()

                    if "youtube.com" in msg_text or "youtu.be" in msg_text:
                        link_cache[sender_id] = msg_text
                        send_message(sender_id, "🔗 Link recognized!\n\nType 'mp3' for audio or 'mp4' for video.")

                    elif msg_text in ['mp3', 'mp4']:
                        if sender_id in link_cache:
                            target_url = link_cache[sender_id]
                            send_message(sender_id, f"⚡ Processing your {msg_text.upper()}...")
                            process_and_send(sender_id, target_url, msg_text)
                            del link_cache[sender_id]
                        else:
                            send_message(sender_id, "❌ No link found. Send a link first.")
                    else:
                        send_message(sender_id, "🤖 Send a YouTube link to begin!")
                else:
                    send_message(sender_id, "😅 Please send a text link!")

    return "EVENT_RECEIVED", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
