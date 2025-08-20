import os
from datetime import datetime
import requests
from flask import Blueprint, request, jsonify

from flask_sqlalchemy import SQLAlchemy

api_bp = Blueprint("api", __name__)
db = SQLAlchemy()

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(50), nullable=False)     # e.g., 'telegram'
    sender = db.Column(db.String(100), nullable=False)      # username or 'You'
    recipient = db.Column(db.String(100), nullable=True)    # e.g., telegram chat_id
    content = db.Column(db.Text, nullable=False)
    direction = db.Column(db.String(10), nullable=False, default="in")  # 'in' or 'out'
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "platform": self.platform,
            "sender": self.sender,
            "recipient": self.recipient,
            "content": self.content,
            "direction": self.direction,
            "timestamp": self.timestamp.isoformat()
        }

# Initialize SQLAlchemy & tables once the blueprint is registered
@api_bp.record_once
def setup(state):
    app = state.app
    # Default to SQLite file if no DB configured in app.py
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite:///site.db")
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    db.init_app(app)
    with app.app_context():
        db.create_all()

# Telegram config
def tg_api_url():
    token = os.getenv("TELEGRAM_TOKEN")
    print("Telegram token loaded:", bool(os.getenv("TELEGRAM_TOKEN")))
    return f"https://api.telegram.org/bot{token}" if token else None

# API routes
@api_bp.route("/api/messages", methods=["GET"])
def get_messages():
    q = Message.query.order_by(Message.timestamp.asc())
    platform = request.args.get("platform")
    if platform:
        q = q.filter(Message.platform == platform.lower())
    msgs = q.all()
    return jsonify([m.to_dict() for m in msgs])

@api_bp.route("/api/messages", methods=["POST"])
def post_message():
    data = request.get_json() or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400

    platform = (data.get("platform") or "telegram").lower()
    sender = data.get("sender") or "You"
    recipient = data.get("recipient")  # Telegram: numeric chat_id

    msg = Message(
        platform=platform,
        sender=sender,
        recipient=recipient,
        content=content,
        direction="out",
    )
    db.session.add(msg)
    db.session.commit()

    # Send to Telegram if configured
    if platform == "telegram" and recipient:
        api = tg_api_url()
        if api:
            try:
                r = requests.post(f"{api}/sendMessage",
                                  json={"chat_id": recipient, "text": content},
                                  timeout=10)
                r.raise_for_status()
            except Exception as e:
                # Log and continue (message already saved)
                print(f"[telegram send] {e}")

    return jsonify(msg.to_dict()), 201

# Telegram webhook (inbound)
@api_bp.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False}), 400

    message = data.get("message")
    if message and "text" in message:
        text = message["text"]
        sender_id = message["from"]["id"]
        sender_name = message["from"].get("username") or message["from"].get("first_name", "Unknown")
        chat_id = message["chat"]["id"]

        # Save to DB
        msg = Message(
            platform="telegram",
            sender=sender_name,
            recipient=str(chat_id),
            content=text,
            direction="in"
        )
        db.session.add(msg)
        db.session.commit()

    return jsonify({"ok": True})
