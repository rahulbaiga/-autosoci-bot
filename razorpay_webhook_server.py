import os
import hmac
import hashlib
from flask import Flask, request, abort
import telebot
from dotenv import load_dotenv
import json
import requests
import logging

load_dotenv()

# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Telegram bot setup
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')
bot = telebot.TeleBot(BOT_TOKEN)

# Razorpay webhook secret
RAZORPAY_WEBHOOK_SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET')
if not RAZORPAY_WEBHOOK_SECRET or RAZORPAY_WEBHOOK_SECRET == 'your_webhook_secret':
    logger.critical('FATAL: RAZORPAY_WEBHOOK_SECRET is not set!')
    raise SystemExit('Webhook secret not set.')

# In-memory mapping: payment_link_id -> chat_id (now persistent)
payment_link_to_chat = {}
MAPPING_FILE = 'payment_link_to_chat.json'
ORDER_MAPPING_FILE = 'payment_link_to_order.json'
payment_link_to_order = {}

def load_mapping():
    global payment_link_to_chat
    if os.path.exists(MAPPING_FILE):
        try:
            with open(MAPPING_FILE, 'r') as f:
                payment_link_to_chat = json.load(f)
            logger.info(f"Loaded mapping from {MAPPING_FILE}")
        except Exception as e:
            logger.error(f"Failed to load mapping: {e}")
    else:
        logger.info(f"No existing mapping file found.")

def save_mapping():
    try:
        with open(MAPPING_FILE, 'w') as f:
            json.dump(payment_link_to_chat, f)
        logger.info(f"Saved mapping to {MAPPING_FILE}")
    except Exception as e:
        logger.error(f"Failed to save mapping: {e}")

def load_order_mapping():
    global payment_link_to_order
    if os.path.exists(ORDER_MAPPING_FILE):
        try:
            with open(ORDER_MAPPING_FILE, 'r') as f:
                payment_link_to_order = json.load(f)
            logger.info(f"Loaded order mapping from {ORDER_MAPPING_FILE}")
        except Exception as e:
            logger.error(f"Failed to load order mapping: {e}")
    else:
        logger.info(f"No existing order mapping file found.")

def save_order_mapping():
    try:
        with open(ORDER_MAPPING_FILE, 'w') as f:
            json.dump(payment_link_to_order, f)
        logger.info(f"Saved order mapping to {ORDER_MAPPING_FILE}")
    except Exception as e:
        logger.error(f"Failed to save order mapping: {e}")

load_mapping()
load_order_mapping()

# Helper: verify Razorpay webhook signature
def verify_signature(request):
    signature = request.headers.get('X-Razorpay-Signature')
    if not signature:
        return False
    body = request.data
    expected_signature = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected_signature)

@app.route('/test', methods=['GET'])
def test_endpoint():
    return 'Webhook server is running', 200

@app.route('/razorpay-webhook', methods=['POST'])
def razorpay_webhook():
    logger.info("Received webhook event")
    load_mapping()         # Always reload mapping from disk
    load_order_mapping()   # Always reload order mapping from disk
    if not verify_signature(request):
        logger.error("Invalid signature")
        if ADMIN_ID:
            try:
                bot.send_message(ADMIN_ID, "[Webhook] Invalid signature received!")
            except Exception as e:
                logger.error(f"Failed to notify admin: {e}")
        abort(400, "Invalid signature")
    data = request.json
    logger.debug(f"Webhook data: {data}")
    if data['event'] == 'payment_link.paid':
        payment_link_id = data['payload']['payment_link']['entity']['id']
        chat_id = payment_link_to_chat.get(payment_link_id)
        order_details = payment_link_to_order.get(payment_link_id)
        if chat_id:
            try:
                # Place agency order if order details are available
                if order_details:
                    service_id = order_details.get('service_id')
                    link = order_details.get('link')
                    quantity = order_details.get('quantity')
                    api_key = os.getenv('AGENCY_API_KEY')
                    url = 'https://nilidon.com/api/v2'
                    params = {
                        'action': 'add',
                        'service': service_id,
                        'link': link,
                        'quantity': quantity,
                        'key': api_key
                    }
                    logger.info(f"Placing agency order: {params}")
                    try:
                        response = requests.get(url, params=params, timeout=15)
                        data = response.json()
                        agency_order_id = data.get('order')
                        logger.info(f"Agency API response: {data}")
                        if agency_order_id:
                            bot.send_message(chat_id, f"\u2705 Payment received! Your order is confirmed and being processed.\nAgency Order ID: <code>{agency_order_id}</code>", parse_mode='HTML')
                        else:
                            bot.send_message(chat_id, "\u2705 Payment received! But failed to place order with agency. Please contact support.")
                            if ADMIN_ID:
                                bot.send_message(ADMIN_ID, f"[Webhook] Payment received for {chat_id}, but failed to place order. Data: {data}")
                    except Exception as e:
                        logger.error(f"Failed to place agency order: {e}")
                        bot.send_message(chat_id, "\u2705 Payment received! But there was an error placing your order. Please contact support.")
                        if ADMIN_ID:
                            bot.send_message(ADMIN_ID, f"[Webhook] Payment received for {chat_id}, but error placing order: {e}")
                else:
                    bot.send_message(chat_id, "\u2705 Payment received! But order details are missing. Please contact support.")
                    if ADMIN_ID:
                        bot.send_message(ADMIN_ID, f"[Webhook] Payment received for {chat_id}, but order details missing.")
                logger.info(f"Notified user {chat_id} for payment link {payment_link_id}")
            except Exception as e:
                logger.error(f"Failed to notify user {chat_id}: {e}")
                if ADMIN_ID:
                    bot.send_message(ADMIN_ID, f"[Webhook] Failed to notify user {chat_id}: {e}")
            # Clean up mapping after notification
            payment_link_to_chat.pop(payment_link_id, None)
            payment_link_to_order.pop(payment_link_id, None)
            save_mapping()
            save_order_mapping()
        else:
            logger.warning(f"No chat_id found for payment link {payment_link_id}")
            if ADMIN_ID:
                bot.send_message(ADMIN_ID, f"[Webhook] No chat_id found for payment link {payment_link_id}")
    return '', 200

if __name__ == '__main__':
    app.run(port=5000) 