import os
import json
import telebot
from telebot import types
from dotenv import load_dotenv
import qrcode
from PIL import Image
import requests
import threading
import time
import logging
import sys
from flask import Flask, request, abort
import hmac
import hashlib
from io import BytesIO

# --- PROFIT MARGIN (GLOBAL) ---
# This will be loaded from a file, with a default of 3 rupees per 1k
PROFIT_MARKUP_PERCENT = 0.0
PROFIT_MARKUP_FILE = 'profit_margin.txt'

# --- Load Environment Variables ---
# This setup works for both local development (with .env) and production (e.g., Railway)
load_dotenv() 

BOT_TOKEN = os.getenv('BOT_TOKEN')
AGENCY_API_KEY = os.getenv('AGENCY_API_KEY')
UPI_ID = os.getenv('UPI_ID')
ADMIN_ID = os.getenv('ADMIN_ID')
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

# --- Logger Setup ---
# Configure logging to file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- Initial Check for Environment Variables ---
# If any variable is missing, log a critical error and exit.
if not all([BOT_TOKEN, AGENCY_API_KEY, UPI_ID, ADMIN_ID]):
    logger.critical("FATAL: Missing one or more required environment variables (BOT_TOKEN, AGENCY_API_KEY, UPI_ID, ADMIN_ID).")
    sys.exit("Critical environment variables are not set. Exiting.")

# --- Bot Initialization ---
bot = telebot.TeleBot(BOT_TOKEN)

# --- SERVICE & STATE MANAGEMENT ---
user_state = {}
services_by_id = {}
loaded_services = {}

# --- ANALYTICS ---
admin_analytics = {'total_orders': 0}

# --- USER TRACKING FOR ANNOUNCEMENTS ---
bot_users = set()
# --- ORDER TRACKING FOR DELAYED CONFIRMATION ---
pending_orders = {}
# --- TRACK PROCESSED ORDERS TO PREVENT MULTIPLE PROCESSING ---
processed_orders = set()

# --- TRACK ALL ORDERS FOR ADMIN PANEL & STATUS NOTIFICATION ---
all_orders = {}  # order_id: {user_id, service, link, quantity, status, ...}

# Import the mapping if using the same file, or import from webhook server if shared
try:
    from razorpay_webhook_server import payment_link_to_chat
    MAPPING_FILE = 'payment_link_to_chat.json'
    ORDER_MAPPING_FILE = 'payment_link_to_order.json'
    payment_link_to_order = {}
    def load_mapping():
        global payment_link_to_chat
        if os.path.exists(MAPPING_FILE):
            try:
                with open(MAPPING_FILE, 'r') as f:
                    payment_link_to_chat = json.load(f)
                logger.info(f"[main.py] Loaded mapping from {MAPPING_FILE}")
            except Exception as e:
                logger.error(f"[main.py] Failed to load mapping: {e}")
        else:
            logger.info(f"[main.py] No existing mapping file found.")
    def save_mapping():
        try:
            with open(MAPPING_FILE, 'w') as f:
                json.dump(payment_link_to_chat, f)
            logger.info(f"[main.py] Saved mapping to {MAPPING_FILE}")
        except Exception as e:
            logger.error(f"[main.py] Failed to save mapping: {e}")
    def load_order_mapping():
        global payment_link_to_order
        if os.path.exists(ORDER_MAPPING_FILE):
            try:
                with open(ORDER_MAPPING_FILE, 'r') as f:
                    payment_link_to_order = json.load(f)
                logger.info(f"[main.py] Loaded order mapping from {ORDER_MAPPING_FILE}")
            except Exception as e:
                logger.error(f"[main.py] Failed to load order mapping: {e}")
        else:
            logger.info(f"[main.py] No existing order mapping file found.")
    def save_order_mapping():
        try:
            with open(ORDER_MAPPING_FILE, 'w') as f:
                json.dump(payment_link_to_order, f)
            logger.info(f"[main.py] Saved order mapping to {ORDER_MAPPING_FILE}")
        except Exception as e:
            logger.error(f"[main.py] Failed to save order mapping: {e}")
    load_mapping()
    load_order_mapping()
except ImportError:
    payment_link_to_chat = {}
    payment_link_to_order = {}
    MAPPING_FILE = 'payment_link_to_chat.json'
    ORDER_MAPPING_FILE = 'payment_link_to_order.json'
    def load_mapping():
        global payment_link_to_chat
        if os.path.exists(MAPPING_FILE):
            try:
                with open(MAPPING_FILE, 'r') as f:
                    payment_link_to_chat = json.load(f)
                logger.info(f"[main.py] Loaded mapping from {MAPPING_FILE}")
            except Exception as e:
                logger.error(f"[main.py] Failed to load mapping: {e}")
        else:
            logger.info(f"[main.py] No existing mapping file found.")
    def save_mapping():
        try:
            with open(MAPPING_FILE, 'w') as f:
                json.dump(payment_link_to_chat, f)
            logger.info(f"[main.py] Saved mapping to {MAPPING_FILE}")
        except Exception as e:
            logger.error(f"[main.py] Failed to save mapping: {e}")
    def load_order_mapping():
        global payment_link_to_order
        if os.path.exists(ORDER_MAPPING_FILE):
            try:
                with open(ORDER_MAPPING_FILE, 'r') as f:
                    payment_link_to_order = json.load(f)
                logger.info(f"[main.py] Loaded order mapping from {ORDER_MAPPING_FILE}")
            except Exception as e:
                logger.error(f"[main.py] Failed to load order mapping: {e}")
        else:
            logger.info(f"[main.py] No existing order mapping file found.")
    def save_order_mapping():
        try:
            with open(ORDER_MAPPING_FILE, 'w') as f:
                json.dump(payment_link_to_order, f)
            logger.info(f"[main.py] Saved order mapping to {ORDER_MAPPING_FILE}")
        except Exception as e:
            logger.error(f"[main.py] Failed to save order mapping: {e}")
    load_mapping()
    load_order_mapping()

def load_profit_margin():
    """Loads the profit markup (in rupees) from a file, otherwise uses default."""
    global PROFIT_MARKUP_PERCENT
    try:
        if os.path.exists(PROFIT_MARKUP_FILE):
            with open(PROFIT_MARKUP_FILE, 'r') as f:
                markup = float(f.read().strip())
                PROFIT_MARKUP_PERCENT = markup
                logger.info(f"Loaded profit markup percent of {PROFIT_MARKUP_PERCENT} from file.")
    except (ValueError, TypeError):
        PROFIT_MARKUP_PERCENT = 0.0 # Default to 0% if file is corrupt
        logger.warning(f"Could not parse profit markup file. Using default: {PROFIT_MARKUP_PERCENT}")

def save_profit_margin(percent):
    """Saves the profit markup (in percent) to a file."""
    global PROFIT_MARKUP_PERCENT
    PROFIT_MARKUP_PERCENT = percent
    with open(PROFIT_MARKUP_FILE, 'w') as f:
        f.write(str(percent))
    logger.info(f"Saved new profit markup percent to file: {percent}")

def categorize_service(api_service):
    """
    Intelligently determines the platform and category for a service from the API.
    Returns: A tuple (platform, category) or (None, None) if uncategorized.
    """
    name = api_service['name'].lower()
    
    # Platform detection
    platform = None
    if 'instagram' in name:
        platform = 'Instagram'
    elif 'youtube' in name:
        platform = 'YouTube'
    elif 'telegram' in name:
        platform = 'Telegram'
    elif 'twitter' in name:
        platform = 'Twitter'
    elif 'facebook' in name:
        platform = 'Facebook'
    elif 'tiktok' in name:
        platform = 'TikTok'

    if not platform:
        return None, None # Skip services for platforms we don't support

    # Category detection (within a platform)
    category = 'Uncategorized' # Default category
    if platform == 'Instagram':
        if 'follower' in name: category = 'Followers'
        elif 'like' in name: category = 'Likes'
        elif 'view' in name: category = 'Views'
        elif 'comment' in name: category = 'Comments'
        elif 'story' in name: category = 'Story'
        elif 'share' in name or 'save' in name: category = 'Shares/Saves'
        elif 'channel' in name: category = 'Channel'
    elif platform == 'YouTube':
        if 'subscribe' in name: category = 'Subscribers'
        elif 'like' in name or ('view' in name and 'short' not in name): category = 'Video Likes/Views'
        elif 'short' in name: category = 'Shorts Likes/Views'
        elif 'live' in name or 'stream' in name: category = 'Livestream'
        elif 'watch' in name or 'time' in name: category = 'Watch Time'
    elif platform == 'Telegram':
        if 'view' in name: category = 'Views'
        elif 'reaction' in name: category = 'Reactions'
        elif 'member' in name: category = 'Members'
    elif platform == 'Twitter':
        if 'view' in name: category = 'Views'
        elif 'like' in name: category = 'Likes'
    elif platform == 'Facebook':
        if 'follower' in name: category = 'Followers'
        elif 'like' in name: category = 'Likes'
        elif 'view' in name: category = 'Views'
    elif platform == 'TikTok':
        if 'follower' in name: category = 'Followers'
        elif 'like' in name: category = 'Likes'
        elif 'save' in name or 'share' in name: category = 'Engagement'
    
    return platform, category

def load_services_from_api():
    """Fetches services from the agency API and structures them for the bot."""
    global loaded_services, services_by_id
    api_key = os.getenv('AGENCY_API_KEY')
    if not api_key:
        logger.critical("FATAL: AGENCY_API_KEY environment variable not set.")
        return False
    url = f"https://nilidon.com/api/v2?action=services&key={api_key}"
    logger.info("Attempting to fetch services from agency API...")
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        api_data = response.json()
        logger.info(f"Successfully fetched {len(api_data)} services from API")
        platforms = {}
        services_by_id.clear()  # Clear old data
        for service_data in api_data:
            platform_name, category_name = categorize_service(service_data)
            if not platform_name:
                logger.debug(f"Skipping service '{service_data['name']}' - platform not supported")
                continue
            if platform_name not in platforms:
                platforms[platform_name] = {}
            if category_name not in platforms[platform_name]:
                platforms[platform_name][category_name] = []
            price_inr = float(service_data['rate'])
            # Apply fixed rupee markup per 1k
            price_with_markup = price_inr + PROFIT_MARKUP_PERCENT
            bot_service = {
                'id': int(service_data['service']),
                'api_service_id': int(service_data['service']),
                'platform': platform_name,
                'category': category_name,
                'service': service_data['name'],
                'price': price_inr,  # Original price from API
                'price_with_margin': price_with_markup,  # Price with fixed rupee markup
                'min': int(service_data.get('min', 0)),
                'max': int(service_data.get('max', 1000000)),
                'description': service_data.get('category', 'No description available.'),
                'refill': service_data.get('refill', False),
                'cancel': service_data.get('cancel', False)
            }
            platforms[platform_name][category_name].append(bot_service)
            services_by_id[bot_service['id']] = bot_service
        loaded_services = platforms
        total_services = len(services_by_id)
        platform_summary = {platform: len(categories) for platform, categories in platforms.items()}
        logger.info(f"Successfully loaded {total_services} services from API:")
        for platform, service_count in platform_summary.items():
            logger.info(f"  - {platform}: {service_count} services")
        return True
    except requests.exceptions.RequestException as e:
        logger.critical(f"FATAL: Could not fetch services from API: {e}")
        return False
    except json.JSONDecodeError:
        logger.critical("FATAL: Failed to parse JSON from agency API response.")
        return False

def find_service_by_id(service_id):
    """Finds a service in the loaded dictionary by its unique ID."""
    return services_by_id.get(service_id)

PLATFORM_EMOJIS = {
    'Instagram': '📸',
    'YouTube': '🎬',
    'Telegram': '✈️',
    'Twitter': '🐦',
    'Facebook': '📘',
    'TikTok': '🎵',
}

# Welcome/onboarding message
WELCOME_TEXT = (
    "👋 <b>Welcome to AUTOSOCI Bot!</b>\n"
    "<b>Grow your social media with 100% organic, real engagement! 💚</b>\n\n"
    "🟢 <b>What can this bot do?</b>\n"
    "Boost your Instagram, YouTube, Telegram, Twitter, Facebook, and TikTok with real followers, likes, views, and more!\n\n"
    "🟢 <b>How does it work?</b>\n"
    "1️⃣ Pick a platform\n"
    "2️⃣ Choose a service\n"
    "3️⃣ Paste your content link\n"
    "4️⃣ Select quantity & see price\n"
    "5️⃣ Pay securely via UPI (QR code)\n"
    "6️⃣ Upload payment screenshot\n"
    "7️⃣ Admin approves & your order is processed!\n\n"
    "💚 <b>All orders are 100% organic and safe. No fake or low-quality methods!</b>\n\n"
    "ℹ️ For YouTube WatchTime, you may need to provide <b>Manager Access</b>. Type /manageraccess or tap the button in service details to learn more!\n\n"
    "Ready to grow? Tap below to get started! 👇"
)

def get_platform_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    # PLATFORM_EMOJIS dictionary for icons
    for p in sorted(loaded_services.keys()):
        emoji = PLATFORM_EMOJIS.get(p, '🔹')
        buttons.append(types.InlineKeyboardButton(f"{emoji} {p}", callback_data=f"platform_{p}"))
    markup.add(*buttons)
    return markup

def get_category_keyboard(platform):
    categories = sorted(loaded_services.get(platform, {}).keys())
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(cat, callback_data=f"category_{platform}_{cat}") for cat in categories]
    markup.add(*buttons)
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_previous"))
    return markup

def get_service_keyboard(platform, category):
    services = loaded_services.get(platform, {}).get(category, [])
    markup = types.InlineKeyboardMarkup(row_width=1)
    for service in services:
        price_per_1000 = float(service['price']) * (1 + PROFIT_MARKUP_PERCENT / 100)
        btn_text = f"{service['service']} (₹{price_per_1000:.2f}/1k)"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"service_{service['id']}"))
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_previous"))
    return markup

def get_details_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_previous"),
        types.InlineKeyboardButton('➡️ Next', callback_data="details_next")
    )
    return markup

def get_link_prompt(platform, service_name):
    # Simple rules for dynamic prompts
    if platform == 'YouTube':
        if 'Subscribe' in service_name or 'Subscriber' in service_name:
            return '🔗 Great! You chose YouTube Subscribers. Please send your YouTube <b>channel link</b>.'
        elif 'View' in service_name or 'Like' in service_name or 'Short' in service_name or 'Livestream' in service_name:
            return '🔗 Great! You chose YouTube Video service. Please send your YouTube <b>video link</b>.'
    elif platform == 'Instagram':
        if 'Follower' in service_name:
            return '🔗 Great! You chose Instagram Followers. Please send your Instagram <b>profile link</b>.'
        elif 'Like' in service_name or 'View' in service_name or 'Comment' in service_name or 'Story' in service_name or 'Share' in service_name or 'Save' in service_name:
            return (
                f"✅ You selected: <b>{service_name}</b>!\n\n"
                "📸 <b>Step 1:</b> Open Instagram and find the post or story you want to boost.\n"
                "🔗 <b>Step 2:</b> Tap \"Share\" and copy the link.\n\n"
                "✍️ <b>Now, please paste your Instagram post or story link below.</b>\n"
                "(Example: https://instagram.com/p/XXXXXXXXX)\n\n"
                "ℹ️ <i>Make sure your post or story is public so we can process your order!</i>"
            )
    elif platform == 'Telegram':
        if 'Member' in service_name:
            return '🔗 Great! You chose Telegram Members. Please send your <b>channel or group link</b>.'
        else:
            return '🔗 Great! You chose Telegram engagement. Please send your <b>post link</b>.'
    elif platform == 'Twitter':
        return '🔗 Great! You chose Twitter. Please send your <b>tweet link</b>.'
    elif platform == 'Facebook':
        if 'Follower' in service_name:
            return '🔗 Great! You chose Facebook Followers. Please send your <b>page or profile link</b>.'
        else:
            return '🔗 Great! You chose Facebook engagement. Please send your <b>post or video link</b>.'
    elif platform == 'TikTok':
        if 'Follower' in service_name:
            return '🔗 Great! You chose TikTok Followers. Please send your <b>profile link</b>.'
        else:
            return '🔗 Great! You chose TikTok engagement. Please send your <b>video link</b>.'
    return f'🔗 Please send your {platform} link.'

def get_link_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_previous"))
    return markup

def get_quantity_keyboard(chat_id=None):
    # Dynamically generate quantity options based on service price so that each is worth at least ₹1
    markup = types.InlineKeyboardMarkup(row_width=2)
    quantities = [100, 500, 1000, 5000]
    if chat_id is not None:
        state = get_current_state(chat_id)
        service = find_service_by_id(state.get('service_id'))
        if service:
            price_per_1k = float(service.get('price', 0))
            valid_quantities = []
            for q in quantities:
                price = calculate_user_price(price_per_1k, q)
                if price >= 1:
                    valid_quantities.append(q)
            if not valid_quantities:
                # fallback: minimum quantity for ₹1
                if price_per_1k > 0:
                    min_q = int((1 / ((price_per_1k + PROFIT_MARKUP_PERCENT / 100) / 1000)) + 0.999)  # round up
                    valid_quantities = [min_q]
                else:
                    valid_quantities = [100]
            for q in valid_quantities:
                markup.add(types.InlineKeyboardButton(str(q), callback_data=f"quantity_{q}"))
        else:
            for q in quantities:
                markup.add(types.InlineKeyboardButton(str(q), callback_data=f"quantity_{q}"))
    else:
        for q in quantities:
            markup.add(types.InlineKeyboardButton(str(q), callback_data=f"quantity_{q}"))
    markup.add(types.InlineKeyboardButton('Custom Quantity', callback_data="custom_quantity"))
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_previous"))
    return markup

def get_summary_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton('✅ Confirm Order', callback_data="confirm_order"))
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_previous"))
    return markup

def get_payment_keyboard(upi_id=None, amount=None, order_id=None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    # Do NOT add Pay with UPI App button, as Telegram does not support upi:// URLs in buttons
    markup.add(
        types.InlineKeyboardButton('✅ Confirm Order', callback_data="confirm_payment_order"),
        types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_previous")
    )
    return markup

def get_payment_proof_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_previous"))
    return markup

def generate_upi_qr(upi_id, amount, order_id):
    upi_link = f"upi://pay?pa={upi_id}&pn=AUTOSOCI&am={amount}&cu=INR&tn=Order{order_id}"
    img = qrcode.make(upi_link)
    file_path = f"assets/payment_proofs/upi_qr_{order_id}.png"
    img.save(file_path)
    return file_path

def place_agency_order(service_id, link, quantity):
    api_key = os.getenv('AGENCY_API_KEY')
    url = 'https://nilidon.com/api/v2'
    params = {
        'action': 'add',
        'service': service_id,
        'link': link,
        'quantity': quantity,
        'key': api_key
    }
    logger.info(f"Placing order with agency. Parameters: {params}")
    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        logger.info(f"Agency API response: {data}")
        return data.get('order')
    except Exception as e:
        logger.error(f"Error placing agency order: {e}")
        return None

def get_order_status(order_id):
    api_key = os.getenv('AGENCY_API_KEY')
    url = 'https://nilidon.com/api/v2'
    params = {
        'action': 'status',
        'order': order_id,
        'key': api_key
    }
    try:
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        return data
    except Exception as e:
        return None

def poll_order_status(user_id, order_id):
    state = user_state.get(user_id)
    if not state:
        return
    import threading
    def poll():
        while True:
            status_data = get_order_status(order_id)
            if not status_data:
                bot.send_message(user_id, "⚠️ Could not fetch order status. Will retry in 1 minute.")
                time.sleep(60)
                continue
            status = status_data.get('status', '').lower()
            if status == 'completed':
                bot.send_message(user_id, f"🎉 <b>Your order (ID: {order_id}) has been successfully delivered!</b>", parse_mode='HTML')
                user_state.pop(user_id, None)
                break
            elif status in ['canceled', 'fail']:
                bot.send_message(user_id, f"❌ <b>Your order (ID: {order_id}) could not be completed. Please contact support.</b>", parse_mode='HTML')
                user_state.pop(user_id, None)
                break
            elif status == 'partial':
                remains = status_data.get('remains', '?')
                bot.send_message(user_id, f"⚠️ <b>Your order (ID: {order_id}) was partially completed. Remaining: {remains}</b>", parse_mode='HTML')
                user_state.pop(user_id, None)
                break
            else:
                # In progress or awaiting
                bot.send_message(user_id, f"⏳ <b>Your order (ID: {order_id}) is still processing. Status: {status_data.get('status', 'Unknown')}</b>", parse_mode='HTML')
                time.sleep(60)  # 1 minute
    threading.Thread(target=poll, daemon=True).start()

def get_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('📊 View Total Orders', callback_data='admin_total_orders'),
        types.InlineKeyboardButton('📦 View All Orders', callback_data='admin_all_orders'),
        types.InlineKeyboardButton('🔄 Bot Status', callback_data='admin_status')
    )
    markup.add(
        types.InlineKeyboardButton("💰 Set Profit Margin", callback_data="set_margin"),
        types.InlineKeyboardButton("📢 Send Announcement", callback_data="send_announcement"),
        types.InlineKeyboardButton("💵 Check API Balance", callback_data="admin_balance")
    )
    # Add Reset Price button
    markup.add(types.InlineKeyboardButton("🧹 Reset Price (No Markup)", callback_data="reset_price"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot_users.add(message.chat.id)
    logger.info(f"User {message.chat.id} started the bot. Checking for admin privileges...")
    
    # Check if the user is an admin
    if str(message.chat.id) in ADMIN_ID.split(','):
        logger.info(f"Admin user {message.chat.id} identified. Showing admin panel.")
        bot.send_message(
            message.chat.id,
            "👋 Welcome, Admin! Here is your control panel.",
            reply_markup=get_admin_keyboard()
        )
        return

    # If not an admin, proceed with the regular user flow
    logger.info(f"Regular user {message.chat.id}. Starting standard user flow.")
    
    # Initialize the user's state stack
    user_state[message.chat.id] = {'step_stack': [{'step': 'platform'}]}
    
    bot.send_message(
        message.chat.id,
        WELCOME_TEXT,
        parse_mode='HTML',
        reply_markup=get_platform_keyboard()
    )

@bot.message_handler(commands=['manageraccess'])
def manager_access_info(message):
    text = (
        "<b>What \"Manager Access\" Means:</b>\n\n"
        "Manager Access means you need to give the service provider (the company/agency) permission to upload videos to your YouTube channel. Here's what happens:\n\n"
        "<b>1. What They Need:</b>\n"
        "• <b>Email Access:</b> They need to be added as a <b>Manager</b> to your YouTube channel\n"
        "• <b>Email:</b> Fastestwatchtime@gmail.com (as mentioned in the service details)\n\n"
        "<b>2. How to Give Manager Access:</b>\n"
        "1️⃣ Go to your <b>YouTube Studio</b>\n"
        "2️⃣ Click on <b>Settings</b> (gear icon)\n"
        "3️⃣ Go to <b>Channel → Advanced settings</b>\n"
        "4️⃣ Under <b>Channel managers</b>, click <b>Add or remove managers</b>\n"
        "5️⃣ Add the email: <b>Fastestwatchtime@gmail.com</b>\n"
        "6️⃣ Give them <b>Manager</b> permissions (not just Editor)\n\n"
        "<b>3. What They Do:</b>\n"
        "• They upload 1 video to your channel\n"
        "• This video gets the watch time and views\n"
        "• After completion, you can make the video public or delete it\n\n"
        "<b>4. Important Notes:</b>\n"
        "✅ Don't remove their access while the order is running\n"
        "✅ Don't delete the video they upload during processing\n"
        "❌ If you delete the video/access, your order will be marked complete without delivery\n"
        "✅ You can make the video public 1 day after completion\n\n"
        "<b>5. Why This Method:</b>\n"
        "YouTube's algorithm is more likely to count watch time from videos uploaded to your own channel.\n"
        "It's more effective than trying to boost watch time on existing videos.\n"
        "This is a common practice in the industry."
    )
    bot.send_message(message.chat.id, text, parse_mode='HTML')

# --- State Management Helpers ---
def get_current_state(chat_id):
    """Gets the user's current state from the top of their step stack."""
    # Initialize if not present
    if chat_id not in user_state or 'step_stack' not in user_state[chat_id]:
        user_state[chat_id] = {'step_stack': [{'step': 'platform'}]}
    return user_state[chat_id]['step_stack'][-1]

def push_state(chat_id, new_state_data):
    """
    Updates the user's state by pushing a new step onto their stack.
    The new step inherits data from the previous step.
    """
    stack = user_state.setdefault(chat_id, {}).setdefault('step_stack', [])
    
    # Inherit from previous state and update with new data
    new_state = (stack[-1] if stack else {}).copy()
    new_state.update(new_state_data)
    
    stack.append(new_state)

def pop_state(chat_id):
    """Pops the current step from the user's stack, returning them to the previous state."""
    stack = user_state.get(chat_id, {}).get('step_stack', [])
    if len(stack) > 1: # Always keep the base 'platform' state
        stack.pop()

# --- NEW CALLBACK HANDLERS FOR INLINE BUTTONS ---

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_previous')
def handle_back_button(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    logger.info(f"User {chat_id} clicked the back button.")
    bot.answer_callback_query(call.id)
    
    pop_state(chat_id)
    prev_state = get_current_state(chat_id)
    step = prev_state.get('step')

    logger.info(f"Returning user {chat_id} to step: {step}")

    try:
        if step == 'platform':
            bot.edit_message_text("👋 <b>Welcome to AUTOSOCI Bot!</b>", chat_id, message_id, parse_mode='HTML', reply_markup=get_platform_keyboard())
        
        elif step == 'category':
            platform = prev_state.get('platform')
            bot.edit_message_text(f"You selected <b>{platform}</b>. Now choose a category:", chat_id, message_id, parse_mode='HTML', reply_markup=get_category_keyboard(platform))
        
        elif step == 'service':
            platform = prev_state.get('platform')
            category = prev_state.get('category')
            bot.edit_message_text(f"You selected <b>{category}</b>. Now choose a service:", chat_id, message_id, parse_mode='HTML', reply_markup=get_service_keyboard(platform, category))

        elif step == 'details':
            show_service_details(chat_id, message_id)

        elif step == 'link':
            service_id = prev_state.get('service_id')
            service = find_service_by_id(service_id)
            prompt = get_link_prompt(service['platform'], service['service'])
            bot.edit_message_text(f"✅ You selected <b>{service['service']}</b>!\n\n{prompt}", chat_id, message_id, parse_mode='HTML', reply_markup=get_link_keyboard())

        elif step == 'quantity':
            bot.edit_message_text("✅ Link received! Now, how much engagement would you like?", chat_id, message_id, reply_markup=get_quantity_keyboard(chat_id))
        
        elif step == 'summary':
            show_order_summary(chat_id, message_id_to_edit=message_id)

        elif step == 'payment':
            # This is tricky because we can't edit a text message into a photo message.
            # So we delete the current message and send a new one.
            bot.delete_message(chat_id, message_id)
            send_payment_instructions(call.message)
        
        else: # Fallback
            bot.edit_message_text("An error occurred. Returning to the start.", chat_id, message_id, reply_markup=get_platform_keyboard())
    except Exception as e:
        logger.error(f"Error handling back button for user {chat_id} to step {step}: {e}")
        bot.edit_message_text("An error occurred, please try again starting from the beginning.", chat_id, message_id, reply_markup=get_platform_keyboard())


@bot.callback_query_handler(func=lambda call: call.data.startswith('platform_'))
def handle_platform_callback(call):
    logger.info(f"User {call.message.chat.id} selected: {call.data}")
    bot.answer_callback_query(call.id)

    platform = call.data.split('_', 1)[1]
    push_state(call.message.chat.id, {'step': 'category', 'platform': platform})
    bot.edit_message_text(f"You selected <b>{platform}</b>. Now choose a category:", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_category_keyboard(platform))


@bot.callback_query_handler(func=lambda call: call.data.startswith('category_'))
def handle_category_callback(call):
    logger.info(f"User {call.message.chat.id} selected: {call.data}")
    bot.answer_callback_query(call.id)

    _, platform, category = call.data.split('_', 2)
    push_state(call.message.chat.id, {'step': 'service', 'category': category})
    bot.edit_message_text(f"You selected <b>{category}</b>. Now choose a service:", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_service_keyboard(platform, category))


@bot.callback_query_handler(func=lambda call: call.data.startswith('service_'))
def handle_service_selection(call):
    """Handles the user's service choice and shows the new details page."""
    logger.info(f"User {call.message.chat.id} selected: {call.data}")
    try:
        service_id = int(call.data.split('_')[1])
        if not find_service_by_id(service_id):
            bot.answer_callback_query(call.id, "❌ Error: Service not found. It might be outdated.", show_alert=True)
            return

        push_state(call.message.chat.id, {'step': 'details', 'service_id': service_id})
        show_service_details(call.message.chat.id, call.message.message_id)

    except (ValueError, IndexError) as e:
        logger.error(f"Error handling service selection for call data '{call.data}': {e}")
        bot.answer_callback_query(call.id, "❌ An unexpected error occurred.", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == 'details_next')
def handle_details_next(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    logger.info(f"User {chat_id} proceeding from details to link submission.")
    bot.answer_callback_query(call.id)

    # Push the 'link' step onto the stack
    push_state(chat_id, {'step': 'link'})
    
    state = get_current_state(chat_id)
    service = find_service_by_id(state.get('service_id'))

    # Check for special cases like YouTube WatchTime that might have different prompts or flows
    if service['platform'] == 'YouTube' and 'WatchTime' in service['service']:
        markup = get_link_keyboard()
        markup.add(types.InlineKeyboardButton('ℹ️ What is Manager Access?', callback_data='manageraccess_info'))
        bot.edit_message_text(f"✅ <b>You selected: {service['service']}</b>\n\n{service['description']}", chat_id, message_id, parse_mode='HTML', reply_markup=markup)
        prompt = get_link_prompt(service['platform'], service['service'])
        bot.send_message(chat_id, f"🔗 <b>Next Step:</b> {prompt}", parse_mode='HTML')
        return

    # Standard service link prompt
    prompt = get_link_prompt(service['platform'], service['service'])
    bot.edit_message_text(
        f"✅ You selected <b>{service['service']}</b>!\n\n{prompt}",
        chat_id,
        message_id,
        parse_mode='HTML',
        reply_markup=get_link_keyboard()
    )

@bot.message_handler(func=lambda m: get_current_state(m.chat.id).get('step') == 'link')
def handle_link(message):
    logger.info(f"User {message.chat.id} submitted link: {message.text}")
    state = get_current_state(message.chat.id)
    
    # Basic link validation
    if not message.text.startswith(('http://', 'https://')):
        bot.reply_to(message, "❌ That doesn't look like a valid link. Please send a valid link starting with http:// or https://")
        return

    state['link'] = message.text
    
    # Check if this is YouTube WatchTime service - skip quantity selection
    service = find_service_by_id(state.get('service_id'))
    if service and service['platform'] == 'YouTube' and 'WatchTime' in service['service']:
        # For YouTube WatchTime, use fixed quantity of 1000 and go directly to summary
        push_state(message.chat.id, {'step': 'summary', 'link': message.text, 'quantity': 1000})
        
        # Show order summary directly
        show_order_summary(message.chat.id)
        return
    
    # For all other services, proceed with quantity selection
    push_state(message.chat.id, {'step': 'quantity', 'link': message.text})
    bot.send_message(message.chat.id, "✅ Link received! Now, how much engagement would you like?", reply_markup=get_quantity_keyboard(message.chat.id))

@bot.callback_query_handler(func=lambda call: call.data.startswith('quantity_') or call.data == 'custom_quantity')
def handle_quantity_callback(call):
    logger.info(f"User {call.message.chat.id} selected: {call.data}")
    bot.answer_callback_query(call.id)
    state = get_current_state(call.message.chat.id)

    if call.data == 'custom_quantity':
        push_state(call.message.chat.id, {'step': 'awaiting_custom_quantity'})
        bot.send_message(call.message.chat.id, "💡 Please enter the desired quantity (e.g., 1000):")
        return

    quantity = int(call.data.split('_')[1])
    process_quantity(call.message, quantity)

@bot.message_handler(func=lambda m: get_current_state(m.chat.id).get('step') == 'awaiting_custom_quantity')
def handle_custom_quantity_input(message):
    """Handles the user's text input for a custom quantity."""
    logger.info(f"User {message.chat.id} submitted custom quantity: {message.text}")
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            raise ValueError("Quantity must be positive.")
        state = get_current_state(message.chat.id)
        service = find_service_by_id(state.get('service_id'))
        if not service:
            bot.reply_to(message, "Service not found. Please start over.")
            return
        price_per_1k = float(service.get('price', 0))
        # Use full price calculation with markup
        total_price = calculate_user_price(price_per_1k, quantity)
        if total_price < 1:
            bot.reply_to(message, "❌ The minimum order value is ₹1. Please enter a higher quantity.")
            bot.send_message(message.chat.id, "Please enter a new quantity (must be at least ₹1 in value):")
            return
        # The 'awaiting_custom_quantity' step is now fulfilled. 
        # We pop it from the history before processing the quantity.
        pop_state(message.chat.id) 
        # Now process the quantity, which will move to the summary step
        process_quantity(message, quantity)
    except (ValueError, TypeError):
        bot.reply_to(message, "❌ Invalid input. Please enter a valid whole number (e.g., 150).")

@bot.callback_query_handler(func=lambda call: call.data == 'confirm_order')
def handle_summary_callback(call):
    logger.info(f"User {call.message.chat.id} selected: {call.data}")
    bot.answer_callback_query(call.id)
    state = get_current_state(call.message.chat.id)
    service = find_service_by_id(state.get('service_id'))
    quantity = state.get('quantity')
    link = state.get('link')
    if not all([service, quantity, link]):
        bot.send_message(call.message.chat.id, "❌ Error: Order information is incomplete. Please start over.")
        return
    # Ask for real phone number
    push_state(call.message.chat.id, {'step': 'awaiting_phone'})
    bot.send_message(
        call.message.chat.id,
        "📱 <b>Enter Your Mobile Number</b>\n\n"
        "Please type your <b>10-digit phone number</b> below to receive your payment link via SMS.\n\n"
        "🔒 <i>Your number is safe and only used for payment confirmation.</i>",
        parse_mode='HTML'
    )

@bot.message_handler(func=lambda m: get_current_state(m.chat.id).get('step') == 'awaiting_phone')
def handle_phone_input(message):
    phone = message.text.strip()
    # Validate phone number: 10 digits, starts with 6-9, no all repeating digits
    if not (phone.isdigit() and len(phone) == 10 and phone[0] in '6789' and len(set(phone)) > 2):
        bot.reply_to(message, "❌ Invalid phone number. Please enter a valid 10-digit Indian mobile number (no repeating digits). Example: 9876543210")
        return
    state = get_current_state(message.chat.id)
    service = find_service_by_id(state.get('service_id'))
    quantity = state.get('quantity')
    link = state.get('link')
    if not all([service, quantity, link]):
        bot.send_message(message.chat.id, "❌ Error: Order information is incomplete. Please start over.")
        return
    # Calculate final amount with profit margin
    final_amount = calculate_user_price(float(service['price']), quantity)
    order_id = f"{message.chat.id}_{int(time.time())}"
    push_state(message.chat.id, {'order_id': order_id, 'step': 'payment'})
    # --- Track order for admin panel ---
    all_orders[order_id] = {
        'user_id': message.chat.id,
        'service': service['service'],
        'platform': service['platform'],
        'category': service['category'],
        'link': link,
        'quantity': quantity,
        'status': 'pending_payment',
        'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        'order_id': order_id
    }
    create_and_send_payment_link(message.chat.id, final_amount, order_id, customer_name="User", customer_email="test@example.com", customer_contact=phone)
    # Send payment instructions with Help button
    instructions = (
        "💳 <b>Payment Instructions</b>\n\n"
        "We have sent a payment link to your phone number via SMS.\n"
        "1️⃣ Open the SMS you received from Razorpay.\n"
        "2️⃣ Click the payment link in the SMS and complete your payment in your browser.\n"
        "3️⃣ Once payment is successful, your order will be processed automatically!\n\n"
        "❗ <b>Do NOT pay twice for the same order.</b>\n\n"
        "If you face any issues, contact support.\n"
        "Join our <a href='https://chat.whatsapp.com/GvLbK18vIfELWWQgKYyoKw'>WhatsApp Support Group</a>."
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❓ Help", callback_data="payment_help"))
    bot.send_message(
        message.chat.id,
        instructions,
        parse_mode="HTML",
        reply_markup=markup,
        disable_web_page_preview=True
    )

@bot.message_handler(content_types=['photo'], func=lambda m: get_current_state(m.chat.id).get('step') == 'payment')
def handle_payment_proof(message):
    logger.info(f"User {message.chat.id} uploaded payment proof.")
    state = get_current_state(message.chat.id)
    service = find_service_by_id(state.get('service_id'))
    quantity = state.get('quantity')
    link = state.get('link')
    order_id = state.get('order_id')

    # Validate required data
    if not all([service, quantity, link, order_id]):
        logger.error(f"Missing required order data for user {message.chat.id}: service={bool(service)}, quantity={quantity}, link={link}, order_id={order_id}")
        bot.reply_to(message, "❌ Error: Order information is incomplete. Please start over.")
        return

    # Calculate prices for admin notification
    actual_cost = (float(service['price']) / 1000) * quantity
    user_price = calculate_user_price(float(service['price']), quantity)
    profit = user_price - actual_cost

    # Ensure payment_proofs directory exists
    payment_proofs_dir = "payment_proofs"
    if not os.path.exists(payment_proofs_dir):
        os.makedirs(payment_proofs_dir)
        logger.info(f"Created payment_proofs directory: {payment_proofs_dir}")

    # Save payment proof and notify admin
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        proof_path = f"{payment_proofs_dir}/payment_{message.chat.id}_{order_id}.jpg"
        
        with open(proof_path, 'wb') as new_file:
            new_file.write(downloaded_file)
        
        logger.info(f"Payment proof saved successfully: {proof_path}")
    except Exception as e:
        logger.error(f"Failed to save payment proof for user {message.chat.id}: {e}")
        bot.reply_to(message, "❌ Error saving payment proof. Please try again.")
        return

    bot.reply_to(message, "✅ Payment screenshot received! Your order is now pending admin verification.")

    admin_analytics['total_orders'] += 1
    admin_message = (
        f"🆕 <b>New Order Pending Approval</b>\n\n"
        f"👤 <b>User ID:</b> {message.chat.id}\n"
        f"🆔 <b>Order ID:</b> {order_id}\n"
        f"📱 <b>Platform:</b> {service['platform']}\n"
        f"📂 <b>Category:</b> {service['category']}\n"
        f"🔧 <b>Service:</b> {service['service']}\n"
        f"🔗 <b>Link:</b> {link}\n"
        f"📊 <b>Quantity:</b> {quantity}\n"
        f"💰 <b>Amount (User):</b> ₹{user_price:.2f}\n"
        f"💵 <b>Cost (Actual):</b> ₹{actual_cost:.2f}\n"
        f"📈 <b>Profit:</b> ₹{profit:.2f}\n\n"
        f"📊 <b>Analytics:</b>\n"
        f"Total Orders Processed: {admin_analytics['total_orders']}\n\n"
        f"📞 <b>Support Team WhatsApp Group:</b>\n"
        f"🔗 https://chat.whatsapp.com/GvLbK18vIfELWWQgKYyoKw\n\n"
        f"Please review the payment proof and approve or reject the order."
    )
    
    markup = types.InlineKeyboardMarkup()
    approve_btn = types.InlineKeyboardButton("✅ Approve", callback_data=f"approve_{message.chat.id}_{order_id}")
    reject_btn = types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_{message.chat.id}_{order_id}")
    markup.add(approve_btn, reject_btn)
    
    # Send the proof image with the caption to all admins
    admin_ids = ADMIN_ID.split(',')
    success_count = 0
    
    try:
        with open(proof_path, 'rb') as proof_photo:
            for admin in admin_ids:
                admin = admin.strip()  # Remove any whitespace
                if not admin:  # Skip empty admin IDs
                    continue
                    
                try:
                    bot.send_photo(admin, proof_photo, caption=admin_message, reply_markup=markup, parse_mode='HTML')
                    success_count += 1
                    logger.info(f"Order notification sent successfully to admin {admin}")
                except Exception as e:
                    logger.error(f"Failed to send order notification to admin {admin}: {e}")
                    
    except Exception as e:
        logger.error(f"Failed to read payment proof file {proof_path}: {e}")
        bot.reply_to(message, "❌ Error processing payment proof. Please contact support.")
        return

    if success_count == 0:
        logger.error(f"No admin notifications were sent successfully for user {message.chat.id}")
        bot.reply_to(message, "⚠️ Warning: Admin notification failed. Please contact support immediately.")
    else:
        logger.info(f"Order notification sent to {success_count}/{len(admin_ids)} admins for user {message.chat.id}")

    push_state(message.chat.id, {'step': 'pending_approval'})

@bot.message_handler(func=lambda m: get_current_state(m.chat.id).get('step') == 'payment' and m.content_type != 'photo')
def prompt_payment_proof(message):
    bot.send_message(message.chat.id, "📸 Please upload your payment screenshot to complete your order.", reply_markup=get_payment_proof_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_admin_approval(call):
    action, user_id, order_id = call.data.split('_', 2)
    user_id = int(user_id)
    
    # Check if this order has already been processed
    if order_id in processed_orders:
        bot.answer_callback_query(call.id, "This order has already been processed.", show_alert=True)
        return
    
    state = get_current_state(user_id)
    if not state or state.get('step') != 'pending_approval':
        bot.answer_callback_query(call.id, "Order not found or already processed.")
        return
    
    # Mark this order as processed immediately to prevent multiple clicks
    processed_orders.add(order_id)
    
    if action == 'approve':
        service = find_service_by_id(state['service_id'])
        service_id = service.get('api_service_id')
        if not service_id:
            logger.error(f"Order processing failed for user {user_id}: 'api_service_id' missing")
            bot.answer_callback_query(call.id, "Service configuration error!", show_alert=True)
            return
        logger.info(f"Placing order for user {user_id} with service_id {service_id}")

        # --- NEW: Check agency balance before placing order ---
        actual_cost = (float(service['price']) / 1000) * state['quantity']
        balance = get_agency_balance()
        if balance is None or balance < actual_cost:
            # Save to pending_orders.json
            pending_orders = load_pending_orders()
            pending_orders.append({
                'user_id': user_id,
                'order_id': order_id,
                'service_id': service_id,
                'link': state['link'],
                'quantity': state['quantity'],
                'timestamp': time.time(),
                'status': 'pending_balance',
                'service': service,
                'state': state
            })
            save_pending_orders(pending_orders)
            # Notify admin only
            admin_msg = (
                f"⚠️ <b>Order NOT placed due to insufficient agency balance.</b>\n\n"
                f"👤 <b>User ID:</b> {user_id}\n"
                f"🆔 <b>Order ID:</b> {order_id}\n"
                f"🔧 <b>Service:</b> {service['service']}\n"
                f"🔗 <b>Link:</b> {state['link']}\n"
                f"📊 <b>Quantity:</b> {state['quantity']}\n"
                f"💵 <b>Cost (Actual):</b> ₹{actual_cost:.2f}\n"
                f"💰 <b>Current API Balance:</b> ₹{balance if balance is not None else 'N/A'}\n\n"
                f"Please recharge the agency balance. The bot will auto-process this order once balance is sufficient."
            )
            for admin in ADMIN_ID.split(','):
                if admin.strip():
                    bot.send_message(admin.strip(), admin_msg, parse_mode='HTML')
            bot.answer_callback_query(call.id, "Order pending: Insufficient agency balance. Admin notified.", show_alert=True)
            return
        # --- END NEW ---

        agency_order_id = place_agency_order(service_id, state['link'], state['quantity'])
        if agency_order_id:
            user_state[user_id] = {'step_stack': [{'step': 'processing', 'agency_order_id': agency_order_id}]}
            bot.send_message(
                user_id, 
                f"✅ <b>Your payment has been approved and order is now being processed!</b>\n"
                f"Agency Order ID: <code>{agency_order_id}</code>\n"
                f"Thank you for your trust!", 
                parse_mode='HTML'
            )
            threading.Thread(target=poll_order_status, args=(user_id, agency_order_id), daemon=True).start()
            # --- Update all_orders status ---
            if order_id in all_orders:
                all_orders[order_id]['status'] = 'processing'
                all_orders[order_id]['agency_order_id'] = agency_order_id
        else:
            bot.answer_callback_query(call.id, "Failed to place order with agency!", show_alert=True)
            bot.send_message(user_id, "❌ <b>There was an error placing your order with the agency. Please contact support.</b>", parse_mode='HTML')
    elif action == 'reject':
        bot.answer_callback_query(call.id, "Order rejected.")
        bot.send_message(user_id, 
            "❌ <b>Your order was not approved for some reason.</b>\n\n"
            "📞 <b>Please contact our support team:</b>\n"
            "🔗 <a href='https://chat.whatsapp.com/GvLbK18vIfELWWQgKYyoKw'>Join Support Group</a>\n\n"
            "💡 <b>What to do:</b>\n"
            "1. Click the link above to join our support group\n"
            "2. Share your order details with the support team\n"
            "3. They will help you resolve the issue\n\n"
            "🆔 <b>Your Order ID:</b> <code>{order_id}</code>", 
            parse_mode='HTML', disable_web_page_preview=True)
        state.clear()
        # --- Update all_orders status ---
        if order_id in all_orders:
            all_orders[order_id]['status'] = 'rejected'
    
    # Only remove the inline keyboard, do not edit the message text
    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"Failed to remove inline keyboard: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "confirm_payment_order")
def handle_confirm_payment_order(call):
    """Handle when user clicks 'Confirm Order' button after seeing payment instructions."""
    logger.info(f"User {call.message.chat.id} confirmed payment order.")
    bot.answer_callback_query(call.id)
    
    # Send a clear and simple message asking for payment screenshot
    confirm_message = (
        "✅ <b>Order Confirmed!</b>\n\n"
        "📸 <b>Please send your payment screenshot now.</b>\n\n"
        "💡 <b>How to:</b>\n"
        "1. Complete the payment using the QR code\n"
        "2. Take a screenshot of the payment\n"
        "3. Send it here"
    )
    
    bot.send_message(call.message.chat.id, confirm_message, parse_mode='HTML')
    
    # Update user state to payment step
    push_state(call.message.chat.id, {'step': 'payment'})

@bot.callback_query_handler(func=lambda call: call.data == 'manageraccess_info')
def send_manageraccess_info_callback(call):
    text = (
        "<b>What \"Manager Access\" Means:</b>\n\n"
        "Manager Access means you need to give the service provider (the company/agency) permission to upload videos to your YouTube channel. Here's what happens:\n\n"
        "<b>1. What They Need:</b>\n"
        "• <b>Email Access:</b> They need to be added as a <b>Manager</b> to your YouTube channel\n"
        "• <b>Email:</b> Fastestwatchtime@gmail.com (as mentioned in the service details)\n\n"
        "<b>2. How to Give Manager Access:</b>\n"
        "1️⃣ Go to your <b>YouTube Studio</b>\n"
        "2️⃣ Click on <b>Settings</b> (gear icon)\n"
        "3️⃣ Go to <b>Channel → Advanced settings</b>\n"
        "4️⃣ Under <b>Channel managers</b>, click <b>Add or remove managers</b>\n"
        "5️⃣ Add the email: <b>Fastestwatchtime@gmail.com</b>\n"
        "6️⃣ Give them <b>Manager</b> permissions (not just Editor)\n\n"
        "<b>3. What They Do:</b>\n"
        "• They upload 1 video to your channel\n"
        "• This video gets the watch time and views\n"
        "• After completion, you can make the video public or delete it\n\n"
        "<b>4. Important Notes:</b>\n"
        "✅ Don't remove their access while the order is running\n"
        "✅ Don't delete the video they upload during processing\n"
        "❌ If you delete the video/access, your order will be marked complete without delivery\n"
        "✅ You can make the video public 1 day after completion\n\n"
        "<b>5. Why This Method:</b>\n"
        "YouTube's algorithm is more likely to count watch time from videos uploaded to your own channel.\n"
        "It's more effective than trying to boost watch time on existing videos.\n"
        "This is a common practice in the industry."
    )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text, parse_mode='HTML')

def show_service_details(chat_id, message_id):
    state = get_current_state(chat_id)
    service = find_service_by_id(state.get('service_id'))

    if not service:
        bot.edit_message_text("An error occurred, please try again.", chat_id, message_id)
        return

    # Use the pre-calculated price with profit margin
    price_per_1000_user = float(service['price']) * (1 + PROFIT_MARKUP_PERCENT / 100)

    # Generate example prices safely and dynamically
    example_prices = ""
    min_q = service.get('min')
    max_q = service.get('max')

    if min_q and max_q and min_q > 0:
        # Dynamically create quantities based on the service's minimum
        multipliers = [1, 2, 5, 10]
        quantities_to_show = [min_q * m for m in multipliers if (min_q * m) <= max_q]
        
        # If no multipliers work (e.g., min is very large), just show the min
        if not quantities_to_show:
            quantities_to_show = [min_q]

        # Determine the service "unit" (e.g., followers, likes)
        service_name_lower = service['service'].lower()
        service_unit = 'units'
        if 'follower' in service_name_lower: service_unit = 'followers'
        elif 'like' in service_name_lower: service_unit = 'likes'
        elif 'view' in service_name_lower: service_unit = 'views'
        elif 'subscribe' in service_name_lower: service_unit = 'subscribers'
        elif 'member' in service_name_lower: service_unit = 'members'
        
        for q in quantities_to_show[:4]: # Show up to 4 examples
            price = (price_per_1000_user / 1000) * q
            example_prices += f"• {q} {service_unit}: <b>₹{price:.2f}</b>\n"
    
    details_text = (
        f"<b>🔍 Service Details: {service['service']}</b>\n\n"
        f"<i>{service.get('description', '')}</i>\n\n"
        f"<b>💰 Price per 1000:</b> ₹{price_per_1000_user:.2f}\n\n"
        f"<b>📊 Example Prices:</b>\n{example_prices if example_prices else 'N/A'}\n"
        f"<b>Minimum Order:</b> {min_q if min_q is not None else 'N/A'}\n"
        f"<b>Maximum Order:</b> {max_q if max_q is not None else 'N/A'}\n\n"
        f"<b>Refill Available:</b> {'✅ Yes' if service.get('refill') else '❌ No'}\n"
        f"<b>Order Cancel:</b> {'✅ Yes' if service.get('cancel') else '❌ No'}\n\n"
    )

    # Add the platform-specific warning for Instagram
    if service.get('platform') == 'Instagram':
        details_text += (
            f"⚠️ <b>Important Notice</b> ⚠️\n"
            f"🌟 Private accounts are not accepted. ❌\n"
            f"🌟 Your account must be public to receive the service. ✅\n\n"
        )

    details_text += "Click 'Next' to provide the link for your order."

    bot.edit_message_text(
        details_text,
        chat_id,
        message_id,
        parse_mode='HTML',
        reply_markup=get_details_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data == 'send_announcement')
def handle_send_announcement_prompt(call):
    if str(call.message.chat.id) not in ADMIN_ID.split(','):
        bot.answer_callback_query(call.id, "You are not authorized.", show_alert=True)
        return
    push_state(call.message.chat.id, {'step': 'awaiting_announcement'})
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"📢 <b>Send Announcement to All Users</b>\n\n"
        f"Please enter your announcement message.\n"
        f"This will be sent to all {len(bot_users)} users who have used the bot.\n\n"
        f"<i>Type your message below:</i>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )

@bot.message_handler(func=lambda m: get_current_state(m.chat.id).get('step') == 'awaiting_announcement')
def handle_announcement_message(message):
    if str(message.chat.id) not in ADMIN_ID.split(','):
        return
    announcement_text = message.text
    success_count = 0
    failed_count = 0
    for user_id in bot_users:
        try:
            bot.send_message(user_id, f"📢 <b>ANNOUNCEMENT</b>\n\n{announcement_text}", parse_mode='HTML')
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to send announcement to user {user_id}: {e}")
            failed_count += 1
    bot.reply_to(
        message, 
        f"✅ <b>Announcement Sent!</b>\n\n"
        f"📊 Results:\n"
        f"✅ Successfully sent: {success_count} users\n"
        f"❌ Failed to send: {failed_count} users\n"
        f"📢 Total users: {len(bot_users)}",
        parse_mode='HTML'
    )
    pop_state(message.chat.id)
    bot.send_message(message.chat.id, "Returning to the admin panel.", reply_markup=get_admin_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def handle_admin_callbacks(call):
    if str(call.message.chat.id) not in ADMIN_ID.split(','):
        return
    
    if call.data == 'admin_total_orders':
        total = admin_analytics.get('total_orders', 0)
        bot.answer_callback_query(call.id)
        bot.edit_message_text(f"📊 Total Orders Processed: {total}", call.message.chat.id, call.message.message_id, reply_markup=get_admin_keyboard())
    elif call.data == 'admin_status':
        bot.answer_callback_query(call.id)
        bot.edit_message_text(f"Bot Status:\n- Running Smoothly\n- Profit Margin: {(PROFIT_MARKUP_PERCENT / 100) * 100:.0f}%", call.message.chat.id, call.message.message_id, reply_markup=get_admin_keyboard())
    elif call.data == 'admin_balance':
        url = f"https://nilidon.com/api/v2?action=balance&key={AGENCY_API_KEY}"
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            balance = data.get('balance', 'N/A')
            currency = data.get('currency', '')
            text = f"💵 <b>API Balance:</b> {balance} {currency}"
        except Exception as e:
            text = f"❌ Failed to fetch API balance.\nError: {e}"
        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_admin_keyboard())
        except Exception as e:
            if "message is not modified" not in str(e):
                raise

@bot.callback_query_handler(func=lambda call: call.data == 'set_margin')
def handle_set_margin_prompt(call):
    """Prompts the admin to set a new profit markup in rupees."""
    if str(call.message.chat.id) not in ADMIN_ID.split(','):
        bot.answer_callback_query(call.id, "You are not authorized.", show_alert=True)
        return
    push_state(call.message.chat.id, {'step': 'awaiting_margin'})
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"Please enter the new profit markup <b>in percent per 1,000 units</b>.\n\n"
        f"For example, to add 10% to every 1,000 units, enter <code>10</code>.\n"
        f"The current markup is <code>{PROFIT_MARKUP_PERCENT:.2f}%</code> per 1,000 units.",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )

@bot.message_handler(func=lambda m: get_current_state(m.chat.id).get('step') == 'awaiting_margin')
def handle_new_margin(message):
    """Saves the new profit markup from the admin."""
    if str(message.chat.id) not in ADMIN_ID.split(','):
        return
    try:
        percent = float(message.text)
        if percent < 0:
            raise ValueError("Markup cannot be negative.")
        save_profit_margin(percent)
        load_services_from_api()  # Reload all services with new markup
        bot.reply_to(message, f"✅ Profit markup has been updated to {percent:.2f}% per 1,000 units. All prices are now updated.")
        pop_state(message.chat.id)
        bot.send_message(message.chat.id, "Returning to the admin panel.", reply_markup=get_admin_keyboard())
    except (ValueError, TypeError):
        bot.reply_to(message, "❌ Invalid input. Please enter a number (e.g., 10).")

def show_order_summary(chat_id, message_id_to_edit=None):
    state = get_current_state(chat_id)
    service = find_service_by_id(state.get('service_id'))
    quantity = state.get('quantity')
    link = state.get('link')

    if not service:
        bot.send_message(chat_id, "An error occurred, please try again.")
        return

    # Calculate final price with profit margin
    final_amount = calculate_user_price(float(service['price']), quantity)

    summary_text = (
        f"<b>📝 Order Summary</b>\n\n"
        f"🟢 Platform: {service['platform']}\n"
        f"🟢 Category: {service['category']}\n"
        f"🟢 Service: {service['service']}\n"
        f"🟢 Link: {link}\n"
        f"🟢 Quantity: {quantity}\n"
        f"💰 <b>Total Amount: ₹{final_amount:.2f}</b>"
    )
    if message_id_to_edit:
        bot.edit_message_text(summary_text, chat_id, message_id_to_edit, parse_mode='HTML', reply_markup=get_summary_keyboard())
    else:
        # When first showing summary, we are coming from quantity selection, so push the state
        push_state(chat_id, {'step': 'summary'})
        bot.send_message(chat_id, summary_text, parse_mode='HTML', reply_markup=get_summary_keyboard())

def process_quantity(message, quantity):
    state = get_current_state(message.chat.id)
    service = find_service_by_id(state.get('service_id'))

    if not service:
        bot.reply_to(message, "An error occurred, service info lost. Please start over.")
        return

    # Validate against min/max limits
    min_q = int(service.get('min', 1))
    max_q = int(service.get('max', 1000000))
    if not (min_q <= quantity <= max_q):
        bot.reply_to(message, f"❌ Quantity must be between {min_q} and {max_q} for this service.")
        # Ask for quantity again
        bot.send_message(message.chat.id, "Please choose a quantity:", reply_markup=get_quantity_keyboard(message.chat.id))
        return

    push_state(message.chat.id, {'quantity': quantity})
    show_order_summary(message.chat.id)

def send_payment_instructions(message):
    state = get_current_state(message.chat.id)
    service = find_service_by_id(state.get('service_id'))
    quantity = state.get('quantity')

    if not all([service, quantity]):
        logger.error(f"Missing service or quantity for user {message.chat.id}")
        bot.reply_to(message, "❌ Error: Order information is incomplete. Please start over.")
        return

    # Calculate final amount with profit margin
    final_amount = calculate_user_price(float(service['price']), quantity)
    
    # Generate unique order ID with timestamp and user ID
    order_id = f"{message.chat.id}_{int(time.time())}"
    
    # Update state with order_id
    push_state(message.chat.id, {'order_id': order_id})
    
    upi_id = os.getenv('UPI_ID')
    amount = final_amount
    
    logger.info(f"Generating QR for user {message.chat.id}, amount {amount}, order_id {order_id}")
    
    try:
        qr_path = generate_upi_qr(upi_id, amount, order_id)
    except Exception as e:
        logger.error(f"Failed to generate QR code for user {message.chat.id}: {e}")
        bot.reply_to(message, "❌ Error generating payment QR code. Please try again.")
        return
    
    caption = (
        f"🟢 <b>Payment Instructions</b>\n"
        f"✅ Amount: <b>₹{amount}</b>\n"
        f"✅ UPI ID: <code>{upi_id}</code>\n"
        f"🆔 Order ID: <code>{order_id}</code>\n\n"
        f"⏳ <b>Please pay within 10 minutes, or your order may expire.</b>\n\n"
        f"💡 <b>How to Pay Quickly:</b>\n"
        f"1️⃣ Tap the QR code to open it in full screen.\n"
        f"2️⃣ Tap the three dots (⋮) in the top right corner.\n"
        f"3️⃣ Select 'Share'.\n"
        f"4️⃣ Choose your payment app (Google Pay, PhonePe, Paytm, etc.).\n"
        f"5️⃣ Complete the payment. The amount will be filled automatically!\n\n"
        f"📋 <b>Or copy UPI ID:</b> Tap on the UPI ID above to copy it in one click!\n\n"
        f"📸 <b>After payment, click 'Confirm Order' and send your payment screenshot.</b>"
    )
    
    try:
        with open(qr_path, "rb") as qr:
            bot.send_photo(message.chat.id, qr, caption=caption, parse_mode="HTML", reply_markup=get_payment_keyboard(upi_id, amount, order_id))
    except Exception as e:
        logger.error(f"Failed to send QR code to user {message.chat.id}: {e}")
        bot.reply_to(message, "❌ Error sending payment instructions. Please try again.")
        return
    
    # Clean up QR code file
    try:
        os.remove(qr_path)
    except Exception as e:
        logger.warning(f"Could not remove QR code file {qr_path}: {e}")
    
    logger.info(f"Payment instructions sent successfully to user {message.chat.id}")

def create_and_send_payment_link(chat_id, amount, order_id, customer_name="User", customer_email="test@example.com", customer_contact="9999999999"):
    # If amount is less than 1, prompt user to re-enter quantity and do not proceed
    if amount < 1:
        bot.send_message(chat_id, "❗ Your order must be more than ₹1. Please try again. Enter a new quantity:")
        # Set state to custom quantity so user can re-enter
        push_state(chat_id, {'step': 'awaiting_custom_quantity'})
        return
    url = "https://api.razorpay.com/v1/payment_links"
    data = {
        "amount": int(amount * 100),  # Razorpay expects paise
        "currency": "INR",
        "accept_partial": False,
        "reference_id": order_id,
        "description": "Order Payment",
        "customer": {
            "name": customer_name,
            "email": customer_email,
            "contact": customer_contact
        },
        "notify": {
            "sms": True,
            "email": False
        },
        "reminder_enable": True
    }
    response = requests.post(url, auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET), json=data)
    result = response.json()
    logger.info(f'Razorpay response: {result}')  # Log the full Razorpay response for debugging
    payment_link_id = result.get('id')
    payment_url = result.get('short_url') or result.get('payment_url')
    if payment_link_id and payment_url:
        payment_link_to_chat[payment_link_id] = chat_id
        # Save order details for webhook server to use
        state = get_current_state(chat_id)
        service_id = state.get('service_id')
        link = state.get('link')
        quantity = state.get('quantity')
        payment_link_to_order[payment_link_id] = {
            'service_id': service_id,
            'link': link,
            'quantity': quantity
        }
        try:
            save_mapping()
            save_order_mapping()
            logger.info(f"[INFO] Saved payment link mapping for {payment_link_id} -> {chat_id}")
        except Exception as e:
            logger.error(f"[ERROR] Could not save payment link mapping: {e}")
        # --- Update all_orders with payment link id ---
        if order_id in all_orders:
            all_orders[order_id]['payment_link_id'] = payment_link_id
            all_orders[order_id]['status'] = 'payment_link_created'
        # --- Send QR code or link based on amount ---
        if amount < 2000:
            # Generate QR code from payment link
            qr = qrcode.QRCode(box_size=10, border=4)
            qr.add_data(payment_url)
            qr.make(fit=True)
            img = qr.make_image(fill='black', back_color='white')
            bio = BytesIO()
            img.save(bio, format='PNG')
            bio.seek(0)
            bot.send_photo(chat_id, photo=bio, caption="Scan this QR code to pay securely via Razorpay.\n\nIf you face any issues, let us know!")
        else:
            bot.send_message(chat_id, f"Click the link below to pay securely via Razorpay:\n{payment_url}")
    else:
        # Only show this error if amount >= 1 (should not happen, but fallback)
        if amount >= 1:
            bot.send_message(chat_id, "❌ Failed to create payment link. Please try again later.")

@bot.message_handler(commands=['check_payment'])
def check_payment_status(message):
    if str(message.from_user.id) != str(ADMIN_ID):
        bot.reply_to(message, "You are not authorized to use this command.")
        return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: /check_payment <payment_link_id>")
        return
    payment_link_id = args[1]
    chat_id = payment_link_to_chat.get(payment_link_id)
    order_details = payment_link_to_order.get(payment_link_id)
    if chat_id:
        bot.reply_to(message, f"Payment link {payment_link_id} is mapped to chat_id {chat_id}. Order details: {order_details}")
    else:
        bot.reply_to(message, f"No mapping found for payment link {payment_link_id}.")

# --- Add admin callback for viewing all orders ---
@bot.callback_query_handler(func=lambda call: call.data == 'admin_all_orders')
def handle_admin_all_orders(call):
    if str(call.message.chat.id) not in ADMIN_ID.split(','):
        return
    bot.answer_callback_query(call.id)
    if not all_orders:
        bot.edit_message_text("No orders yet.", call.message.chat.id, call.message.message_id, reply_markup=get_admin_keyboard())
        return
    # Show a summary of all orders (last 10 for brevity)
    order_list = list(all_orders.values())[-10:]
    msg = '<b>📦 Last 10 Orders:</b>\n\n'
    for o in order_list:
        msg += (f"<b>Order ID:</b> {o['order_id']}\n"
                f"<b>User:</b> {o['user_id']}\n"
                f"<b>Service:</b> {o['service']}\n"
                f"<b>Platform:</b> {o['platform']}\n"
                f"<b>Quantity:</b> {o['quantity']}\n"
                f"<b>Status:</b> {o.get('status', 'unknown')}\n"
                f"<b>Created:</b> {o.get('created_at', '')}\n"
                f"{'-'*20}\n")
    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_admin_keyboard())

# --- Background thread to notify admin of order statuses every 5 minutes ---
def admin_order_status_notifier():
    while True:
        try:
            if all_orders:
                status_msgs = []
                for order_id, o in all_orders.items():
                    agency_order_id = o.get('agency_order_id')
                    if agency_order_id:
                        status_data = get_order_status(agency_order_id)
                        status = status_data.get('status', 'unknown') if status_data else 'unknown'
                        o['status'] = status
                        status_msgs.append(f"Order {order_id}: {status}")
                if status_msgs:
                    msg = '<b>⏰ Order Status Update:</b>\n' + '\n'.join(status_msgs)
                    for admin in ADMIN_ID.split(','):
                        admin = admin.strip()
                        if admin:
                            try:
                                bot.send_message(admin, msg, parse_mode='HTML')
                            except Exception as e:
                                logger.error(f"Failed to send status update to admin {admin}: {e}")
        except Exception as e:
            logger.error(f"Error in admin_order_status_notifier: {e}")
        time.sleep(300)  # 5 minutes

# --- FLASK WEBHOOK SERVER (MERGED FROM razorpay_webhook_server.py) ---
app = Flask(__name__)

RAZORPAY_WEBHOOK_SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET')
if not RAZORPAY_WEBHOOK_SECRET or RAZORPAY_WEBHOOK_SECRET == 'your_webhook_secret':
    logger.critical('FATAL: RAZORPAY_WEBHOOK_SECRET is not set!')
    raise SystemExit('Webhook secret not set.')

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
                            # Build order info
                            user_id = order_details.get('user_id', chat_id)
                            order_id = order_details.get('order_id', 'N/A')
                            platform = order_details.get('platform', 'N/A')
                            category = order_details.get('category', 'N/A')
                            service = order_details.get('service', 'N/A')
                            link = order_details.get('link', 'N/A')
                            quantity = order_details.get('quantity', 'N/A')
                            amount = order_details.get('amount', 'N/A')

                            # User message
                            user_message = (
                                "🎉 <b>Payment Successful!</b> 🎉\n\n"
                                "✅ <b>Your order is confirmed and being processed.</b>\n"
                                f"🆔 <b>Order ID:</b> <code>{order_id}</code>\n"
                                f"📱 <b>Platform:</b> {platform}\n"
                                f"📂 <b>Category:</b> {category}\n"
                                f"🔧 <b>Service:</b> {service}\n"
                                f"🔗 <b>Link:</b> {link}\n"
                                f"📊 <b>Quantity:</b> {quantity}\n"
                                f"💰 <b>Amount:</b> ₹{amount}\n"
                                f"🏷️ <b>Agency Order ID:</b> <code>{agency_order_id}</code>\n\n"
                                "⏳ <b>Status:</b> Processing\n\n"
                                "🚀 <b>We will notify you as soon as your order is delivered!</b>\n"
                                "Thank you for choosing AUTOSOCI! 💚\n\n"
                                "📞 <b>Support:</b> https://chat.whatsapp.com/GvLbK18vIfELWWQgKYyoKw"
                            )
                            bot.send_message(chat_id, user_message, parse_mode='HTML')

                            # Admin message (NO WhatsApp link)
                            admin_message = (
                                "🆕 <b>New Paid Order Received!</b> 🎉\n\n"
                                f"👤 <b>User ID:</b> {user_id}\n"
                                f"🆔 <b>Order ID:</b> {order_id}\n"
                                f"📱 <b>Platform:</b> {platform}\n"
                                f"📂 <b>Category:</b> {category}\n"
                                f"🔧 <b>Service:</b> {service}\n"
                                f"🔗 <b>Link:</b> {link}\n"
                                f"📊 <b>Quantity:</b> {quantity}\n"
                                f"💰 <b>Amount:</b> ₹{amount}\n"
                                f"🏷️ <b>Agency Order ID:</b> <code>{agency_order_id}</code>\n\n"
                                "⏳ <b>Status:</b> Processing\n"
                            )
                            for admin in ADMIN_ID.split(','):
                                admin = admin.strip()
                                if admin:
                                    try:
                                        bot.send_message(admin, admin_message, parse_mode='HTML')
                                    except Exception as e:
                                        logger.error(f"Failed to send order info to admin {admin}: {e}")
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

# --- RUN BOTH FLASK AND TELEGRAM BOT ---
def run_flask():
    app.run(host="0.0.0.0", port=5000)

def run_bot():
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

@bot.callback_query_handler(func=lambda call: call.data == "payment_help")
def handle_payment_help(call):
    # Send the screenshot and a helpful caption
    screenshot_path = "assets/step 1.jpg"  # or whichever screenshot you want to send
    caption = (
        "🖼️ <b>How to Pay Using the Payment Link</b>\n\n"
        "1️⃣ Open the SMS from Razorpay and tap the payment link.\n"
        "2️⃣ Complete the payment in your browser.\n"
        "3️⃣ If you face any issues, contact support."
    )
    try:
        with open(screenshot_path, "rb") as photo:
            bot.send_photo(call.message.chat.id, photo, caption=caption, parse_mode="HTML")
    except Exception as e:
        bot.send_message(call.message.chat.id, "❌ Unable to send help screenshot. Please contact support.")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'reset_price')
def handle_reset_price(call):
    if str(call.message.chat.id) not in ADMIN_ID.split(','):
        bot.answer_callback_query(call.id, "You are not authorized.", show_alert=True)
        return
    save_profit_margin(0)  # Set profit margin to 0
    load_services_from_api()  # Reload all services with no markup
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        "✅ All service prices have been reset to agency rates (no markup). All user-facing prices now match the agency API.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=get_admin_keyboard()
    )

def calculate_user_price(base_price, quantity):
    # base_price is per 1000 units
    total_base = (base_price / 1000) * quantity
    return total_base * (1 + PROFIT_MARKUP_PERCENT / 100)

def get_agency_balance():
    """Fetches the current agency API balance as a float. Returns None on error."""
    url = f"https://nilidon.com/api/v2?action=balance&key={AGENCY_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        balance = float(data.get('balance', 0))
        return balance
    except Exception as e:
        logger.error(f"Failed to fetch agency API balance: {e}")
        return None

PENDING_ORDERS_FILE = 'pending_orders.json'

def load_pending_orders():
    try:
        with open(PENDING_ORDERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_pending_orders(orders):
    with open(PENDING_ORDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)

def process_pending_orders_periodically():
    while True:
        try:
            pending_orders = load_pending_orders()
            if not pending_orders:
                time.sleep(60)
                continue
            balance = get_agency_balance()
            if balance is None:
                logger.warning("Could not fetch agency balance for pending order processing.")
                time.sleep(60)
                continue
            new_pending = []
            for order in pending_orders:
                actual_cost = (float(order['service']['price']) / 1000) * order['quantity']
                if balance >= actual_cost:
                    agency_order_id = place_agency_order(order['service_id'], order['link'], order['quantity'])
                    if agency_order_id:
                        # Notify user as usual
                        user_state[order['user_id']] = {'step_stack': [{'step': 'processing', 'agency_order_id': agency_order_id}]}
                        bot.send_message(
                            order['user_id'],
                            f"✅ <b>Your payment has been approved and order is now being processed!</b>\n"
                            f"Agency Order ID: <code>{agency_order_id}</code>\n"
                            f"Thank you for your trust!",
                            parse_mode='HTML'
                        )
                        threading.Thread(target=poll_order_status, args=(order['user_id'], agency_order_id), daemon=True).start()
                        # Update all_orders status if present
                        if order['order_id'] in all_orders:
                            all_orders[order['order_id']]['status'] = 'processing'
                            all_orders[order['order_id']]['agency_order_id'] = agency_order_id
                        # Deduct the cost from balance for this loop
                        balance -= actual_cost
                    else:
                        # If failed to place order, keep it pending
                        new_pending.append(order)
                else:
                    # Still not enough balance, keep it pending
                    new_pending.append(order)
            if len(new_pending) != len(pending_orders):
                save_pending_orders(new_pending)
        except Exception as e:
            logger.error(f"Error in processing pending orders: {e}")
        time.sleep(60)

# Start the background thread when the bot starts
threading.Thread(target=process_pending_orders_periodically, daemon=True).start()

if __name__ == '__main__':
    logger.info("=== BOT IS STARTING ===")
    try:
        # Create necessary directories
        directories = ['assets/payment_proofs', 'payment_proofs']
        for directory in directories:
            if not os.path.exists(directory):
                os.makedirs(directory)
                logger.info(f"Created directory: {directory}")
        load_profit_margin()
        # This check ensures that if the API call fails, the bot will not start.
        if not load_services_from_api():
            logger.critical("Bot cannot start without services. Please check the AGENCY_API_KEY and the provider's status.")
            sys.exit("Could not load services from the agency API. Exiting.")
        # --- Start Flask in a thread ---
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        logger.info("Bot polling started...")
        # Use faster polling for more responsive bot with better timeout handling
        run_bot()
        # --- Start the admin order status notifier thread at startup ---
        threading.Thread(target=admin_order_status_notifier, daemon=True).start()
    except Exception as e:
        logger.critical(f"An unrecoverable error occurred: {e}", exc_info=True)
    finally:
        logger.info("=== BOT STOPPED ===") 