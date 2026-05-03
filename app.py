import os
import requests
import yt_dlp
from flask import Flask, request
from cachetools import TTLCache

app = Flask(__name__)

# Cache: Stores user links for 10 minutes (prevents data loss if user is slow)
link_cache = TTLCache(maxsize=100, ttl=600)

# Environment Variables (Set these in Render Dashboard)
PAGE_ACCESS_TOKEN = os.environ.get('PAGE_ACCESS_TOKEN')
VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')

# --- FACEBOOK API HELPERS ---

def send_action(recipient_id, action):
    """Actions: 'mark_seen', 'typing_on', 'typing_off'"""
    url = f"https://graph.facebook.com/v17.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": recipient_id}, "sender_action": action}
    requests.post(url, json=payload)

def send_message(recipient_id, text):
    """Sends a professional text response."""
    url = f"https://graph.facebook.com/v17.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    requests.post(url, json=payload)

# --- DOWNLOADER LOGIC ---

def process_and_send(recipient_id, url, mode):
    """Handles download, upload to FB, and local cleanup."""
    ext = 'mp3' if mode == 'mp3' else 'mp4'
    filename = f"dl_{recipient_id}.{ext}"
    
    # Show typing indicator while downloading
    send_action(recipient_id, "typing_on")
    
    ydl_opts = {
        'format': 'bestaudio/best' if mode == 'mp3' else 'best[ext=mp4]/best',
        'outtmpl': filename,
        'max_filesize': 25000000, # Facebook's strict 25MB limit
        'quiet': True,
        'no_warnings': True
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
        
        # Upload the file to Facebook
        fb_url = f"https://graph.facebook.com/v17.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
        with open(filename, 'rb') as f:
            files = {
                'recipient': (None, '{"id":"' + recipient_id + '"}'),
                'message': (None, '{"attachment":{"type":"file", "payload":{}}}'),
                'filedata': (filename, f, 'audio/mpeg' if mode == 'mp3' else 'video/mp4')
            }
            r = requests.post(fb_url, files=files)
        
        if r.status_code == 200:
            send_message(recipient_id, "✅ Done! Your file is ready.")
        else:
            send_message(recipient_id, "⚠️ FB rejected the file. It might be over 25MB.")
            
    except Exception as e:
        send_message(recipient_id, "❌ Error: Video too large, restricted, or link expired.")
    finally:
        # Hide typing indicator and delete local file to save Render disk space
        send_action(recipient_id, "typing_off")
        if os.path.exists(filename):
            os.remove(filename)

# --- WEBHOOK ROUTES ---

@app.route('/')
def home():
    # Simple status page for Render health checks
    return "<h1>bot running</h1>", 200

@app.route('/webhook', methods=['GET'])
def verify():
    # Facebook Webhook Verification
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verification token mismatch", 403

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data.get("object") == "page":
        for entry in data["entry"]:
            for event in entry.get("messaging", []):
                sender_id = event["sender"]["id"]
                
                # Mark as seen immediately
                send_action(sender_id, "mark_seen")

                if "message" in event and "text" in event["message"]:
                    msg_text = event["message"]["text"].strip()
                    lower_text = msg_text.lower()

                    # 1. Check for Full YouTube Link
                    if "youtube.com" in lower_text or "youtu.be" in lower_text:
                        link_cache[sender_id] = msg_text
                        send_message(sender_id, "🔗 Link recognized!\n\nChoose: Type 'mp3' (Audio) or 'mp4' (Video).")

                    # 2. Check for 11-char Video ID (Bypass FB link block)
                    elif len(msg_text) == 11 and " " not in msg_text:
                        link_cache[sender_id] = f"https://www.youtube.com/watch?v={msg_text}"
                        send_message(sender_id, f"✅ Video ID: {msg_text}\n\nChoose: Type 'mp3' (Audio) or 'mp4' (Video)?")

                    # 3. Check for Choice (mp3/mp4)
                    elif lower_text in ['mp3', 'mp4']:
                        if sender_id in link_cache:
                            send_message(sender_id, f"⚡ Processing your {lower_text.upper()}...")
                            process_and_send(sender_id, link_cache[sender_id], lower_text)
                            del link_cache[sender_id]
                        else:
                            send_message(sender_id, "❌ No link found. Please send a Video ID first.")

                    # 4. Professional Guide (Fallback)
                    else:
                        guide = (
                            "🤖 **YouTube Downloader Bot**\n\n"
                            "• Paste a link OR just the **Video ID**.\n"
                            "• Example ID: `IZi9BIstRRY`\n\n"
                            "Then reply with **mp3** or **mp4**!"
                        )
                        send_message(sender_id, guide)

    return "EVENT_RECEIVED", 200

if __name__ == '__main__':
    # Render provides the PORT env var automatically
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
