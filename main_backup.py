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

# --- PROFIT MARGIN (GLOBAL) ---
# This will be loaded from a file, with a default of 40%
PROFIT_MARGIN = 1.4
PROFIT_MARGIN_FILE = 'profit_margin.txt'

# --- Load Environment Variables ---
# This setup works for both local development (with .env) and production (e.g., Railway)
load_dotenv() 

BOT_TOKEN = os.getenv('BOT_TOKEN')
AGENCY_API_KEY = os.getenv('AGENCY_API_KEY')
UPI_ID = os.getenv('UPI_ID')
ADMIN_ID = os.getenv('ADMIN_ID')

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

def load_profit_margin():
    """Loads the profit margin from a file, otherwise uses default."""
    global PROFIT_MARGIN
    try:
        if os.path.exists(PROFIT_MARGIN_FILE):
            with open(PROFIT_MARGIN_FILE, 'r') as f:
                margin = float(f.read().strip())
                PROFIT_MARGIN = margin
                logger.info(f"Loaded profit margin of {PROFIT_MARGIN} from file.")
    except (ValueError, TypeError):
        PROFIT_MARGIN = 1.4 # Default to 1.4 if file is corrupt
        logger.warning(f"Could not parse profit margin file. Using default: {PROFIT_MARGIN}")

def save_profit_margin(margin):
    """Saves the profit margin to a file."""
    global PROFIT_MARGIN
    PROFIT_MARGIN = margin
    with open(PROFIT_MARGIN_FILE, 'w') as f:
        f.write(str(margin))
    logger.info(f"Saved new profit margin to file: {margin}")

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

            # Treat the 'rate' from the API as the direct price in INR.
            price_inr = float(service_data['rate'])
            
            # Apply profit margin to the price for user display
            price_with_margin = price_inr * PROFIT_MARGIN

            bot_service = {
                'id': int(service_data['service']),
                'api_service_id': int(service_data['service']),
                'platform': platform_name,
                'category': category_name,
                'service': service_data['name'],
                'price': price_inr,  # Original price from API
                'price_with_margin': price_with_margin,  # Price with profit margin
                'min': int(service_data.get('min', 0)),
                'max': int(service_data.get('max', 1000000)),
                'description': service_data.get('category', 'No description available.'),
                'refill': service_data.get('refill', False),
                'cancel': service_data.get('cancel', False)
            }
            
            platforms[platform_name][category_name].append(bot_service)
            services_by_id[bot_service['id']] = bot_service

        loaded_services = platforms
        
        # Log summary of loaded services
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
        # Use the pre-calculated price with profit margin
        price_per_1000 = service.get('price_with_margin', float(service['price']) * PROFIT_MARGIN)
        btn_text = f"{service['service']} (₹{price_per_1000:.2f}/1k)"
        # Use the unique service ID in the callback_data
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
            return '🔗 Great! You chose Instagram engagement. Please send your Instagram <b>post or story link</b>.'
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

def get_quantity_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('100', callback_data="quantity_100"),
        types.InlineKeyboardButton('500', callback_data="quantity_500"),
        types.InlineKeyboardButton('1000', callback_data="quantity_1000"),
        types.InlineKeyboardButton('5000', callback_data="quantity_5000")
    )
    markup.add(types.InlineKeyboardButton('Custom Quantity', callback_data="custom_quantity"))
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_previous"))
    return markup

def get_summary_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton('✅ Confirm Order', callback_data="confirm_order"))
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_previous"))
    return markup

def get_payment_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_previous"))
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
    while True:
        status_data = get_order_status(order_id)
        if not status_data:
            bot.send_message(user_id, "⚠️ Could not fetch order status. Will retry in 5 minutes.")
            time.sleep(300)
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
            time.sleep(300)  # 5 minutes

def get_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('📊 View Total Orders', callback_data='admin_total_orders'),
        types.InlineKeyboardButton('🔄 Bot Status', callback_data='admin_status')
    )
    markup.add(
        types.InlineKeyboardButton("💰 Set Profit Margin", callback_data="set_margin")
    )
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
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
            bot.edit_message_text("✅ Link received! Now, how much engagement would you like?", chat_id, message_id, reply_markup=get_quantity_keyboard())
        
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
    bot.send_message(message.chat.id, "✅ Link received! Now, how much engagement would you like?", reply_markup=get_quantity_keyboard())

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
    
    push_state(call.message.chat.id, {'step': 'payment'})
    congrats_msg = (
        "🎉 <b>Congratulations!</b> 🎉\n\n"
        "Thank you for choosing <b>AUTOSOCI</b> to boost your social presence! 🚀\n"
        "You're just one step away from growing your account with 100% organic results. 💚\n\n"
        "Let's complete your order and get you started on your journey to success! 🌟"
    )
    bot.send_message(call.message.chat.id, congrats_msg, parse_mode='HTML')
    send_payment_instructions(call.message)

@bot.message_handler(content_types=['photo'], func=lambda m: get_current_state(m.chat.id).get('step') == 'payment')
def handle_payment_proof(message):
    logger.info(f"User {message.chat.id} uploaded payment proof.")
    state = get_current_state(message.chat.id)
    service = find_service_by_id(state.get('service_id'))
    quantity = state.get('quantity')
    link = state.get('link')

    # Calculate prices for admin notification
    actual_cost = (float(service['price']) / 1000) * quantity
    user_price = actual_cost * PROFIT_MARGIN
    profit = user_price - actual_cost

    # Save payment proof and notify admin
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    proof_path = f"payment_proofs/payment_{message.chat.id}_{state['order_id']}.jpg"
    with open(proof_path, 'wb') as new_file:
        new_file.write(downloaded_file)

    bot.reply_to(message, "✅ Payment screenshot received! Your order is now pending admin verification.")

    admin_analytics['total_orders'] += 1
    admin_message = (
        f"New Order Pending Approval\n"
        f"🟢 User ID: {message.chat.id}\n"
        f"🟢 Platform: {service['platform']}\n"
        f"🟢 Category: {service['category']}\n"
        f"🟢 Service: {service['service']}\n"
        f"🟢 Link: {link}\n"
        f"🟢 Quantity: {quantity}\n"
        f"💰 Amount (User): ₹{user_price:.2f}\n"
        f"💵 Cost (Actual): ₹{actual_cost:.2f}\n"
        f"📈 Profit: ₹{profit:.2f}\n\n"
        f"Analytics:\n"
        f"📊 Total Orders Processed: {admin_analytics['total_orders']}\n\n"
        f"Support Team WhatsApp Group:\n"
        f"🔗 Join Support Group (https://chat.whatsapp.com/GvLbK18vIfELWWQgKYyoKw)\n\n"
        f"Please review the payment proof and approve or reject the order."
    )
    
    markup = types.InlineKeyboardMarkup()
    approve_btn = types.InlineKeyboardButton("✅ Approve", callback_data=f"approve_{message.chat.id}_{state['order_id']}")
    reject_btn = types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_{message.chat.id}_{state['order_id']}")
    markup.add(approve_btn, reject_btn)
    
    # Send the proof image with the caption to all admins
    with open(proof_path, 'rb') as proof_photo:
        for admin in ADMIN_ID.split(','):
            try:
                bot.send_photo(admin, proof_photo, caption=admin_message, reply_markup=markup)
            except Exception as e:
                logger.error(f"Failed to send order notification to admin {admin}: {e}")

    push_state(message.chat.id, {'step': 'pending_approval'})

@bot.message_handler(func=lambda m: get_current_state(m.chat.id).get('step') == 'payment' and m.content_type != 'photo')
def prompt_payment_proof(message):
    bot.send_message(message.chat.id, "📸 Please upload your payment screenshot to complete your order.", reply_markup=get_payment_proof_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_admin_approval(call):
    action, user_id, order_id = call.data.split('_', 2)
    user_id = int(user_id)
    state = get_current_state(user_id)
    if not state or state.get('step') != 'pending_approval':
        bot.answer_callback_query(call.id, "Order not found or already processed.")
        return
    if action == 'approve':
        bot.answer_callback_query(call.id, "Order approved!")
        
        service = find_service_by_id(state['service_id'])
        service_id = service.get('api_service_id')
        
        if not service_id:
            logger.error(f"Order approval failed for user {user_id}: 'api_service_id' missing for service '{service.get('service')}'")
            bot.send_message(user_id, "❌ <b>There was a configuration error with this service. Please contact support.</b>", parse_mode='HTML')
            bot.send_message(call.message.chat.id, f"<b>APPROVAL FAILED:</b> The service '{service.get('service')}' is missing its 'api_service_id' in the loaded configuration. This can happen if the agency API did not provide an ID for this service. Please check the bot's startup logs.", parse_mode='HTML')
            return

        link = state['link']
        quantity = state['quantity']
        
        logger.info(f"Attempting to place order for user {user_id} with service_id {service_id}")
        order_id = place_agency_order(service_id, link, quantity)
        
        if order_id:
            state['agency_order_id'] = order_id
            bot.send_message(user_id, f"✅ <b>Your payment has been approved!</b>\nYour order is now being processed.\nOrder ID: <code>{order_id}</code>\nThank you for your trust!", parse_mode='HTML')
            push_state(user_id, {'step': 'processing'})
            # Start polling in a background thread
            threading.Thread(target=poll_order_status, args=(user_id, order_id), daemon=True).start()
        else:
            bot.send_message(user_id, "❌ <b>There was an error placing your order with the agency. Please contact support.</b>", parse_mode='HTML')
            state.clear()
    elif action == 'reject':
        bot.answer_callback_query(call.id, "Order rejected.")
        # Notify user
        bot.send_message(user_id, "❌ <b>Your payment was not approved.</b>\nPlease try again or contact support if you believe this is a mistake.", parse_mode='HTML')
        state.clear()

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
        bot.edit_message_text(f"Bot Status:\n- Running Smoothly\n- Profit Margin: {(PROFIT_MARGIN - 1)*100:.0f}%", call.message.chat.id, call.message.message_id, reply_markup=get_admin_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == 'set_margin')
def handle_set_margin_prompt(call):
    """Prompts the admin to set a new profit margin."""
    if str(call.message.chat.id) not in ADMIN_ID.split(','):
        bot.answer_callback_query(call.id, "You are not authorized.", show_alert=True)
        return
    
    push_state(call.message.chat.id, {'step': 'awaiting_margin'})
    
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"Please enter the new profit margin <b>percentage</b>.\n\n"
        f"For example, for a 40% margin, enter `40`.\n"
        f"The current margin is `{(PROFIT_MARGIN - 1) * 100:.0f}%`.",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )

@bot.message_handler(func=lambda m: get_current_state(m.chat.id).get('step') == 'awaiting_margin')
def handle_new_margin(message):
    """Saves the new profit margin from the admin."""
    if str(message.chat.id) not in ADMIN_ID.split(','):
        return

    try:
        margin_percent = float(message.text)
        if margin_percent < 0:
            raise ValueError("Margin cannot be negative.")
        
        new_margin = 1 + (margin_percent / 100.0)
        save_profit_margin(new_margin)
        
        bot.reply_to(message, f"✅ Profit margin has been updated to {margin_percent}%.")
        
        pop_state(message.chat.id) 
        bot.send_message(message.chat.id, "Returning to the admin panel.", reply_markup=get_admin_keyboard())

    except (ValueError, TypeError):
        bot.reply_to(message, "❌ Invalid input. Please enter a number (e.g., 40).")

def show_order_summary(chat_id, message_id_to_edit=None):
    state = get_current_state(chat_id)
    service = find_service_by_id(state.get('service_id'))
    quantity = state.get('quantity')
    link = state.get('link')

    if not service:
        bot.send_message(chat_id, "An error occurred, please try again.")
        return

    # Calculate final price with profit margin
    final_amount = (float(service['price']) / 1000) * quantity * PROFIT_MARGIN

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
        bot.send_message(message.chat.id, "Please choose a quantity:", reply_markup=get_quantity_keyboard())
        return

    push_state(message.chat.id, {'quantity': quantity})
    show_order_summary(message.chat.id)

def send_payment_instructions(message):
    state = get_current_state(message.chat.id)
    service = find_service_by_id(state.get('service_id'))
    quantity = state.get('quantity')

    # Calculate final amount with profit margin
    final_amount = (float(service['price']) / 1000) * quantity * PROFIT_MARGIN
    
    order_id = f"{message.chat.id}_{int(time.time())}"
    state['order_id'] = order_id
    
    upi_id = os.getenv('UPI_ID')
    amount = final_amount
    
    logger.info(f"Generating QR for user {message.chat.id}, amount {amount}, order_id {order_id}")
    qr_path = generate_upi_qr(upi_id, amount, order_id)
    
    caption = (
        f"🟢 <b>Payment Instructions</b>\n"
        f"✅ Amount: <b>₹{amount}</b>\n"
        f"✅ UPI ID: <b>{upi_id}</b>\n\n"
        f"⏳ <b>Please pay within 10 minutes, or your order may expire.</b>\n\n"
        f"💡 <b>How to Pay Quickly:</b>\n"
        f"1️⃣ Tap the QR code to open it in full screen.\n"
        f"2️⃣ Tap the three dots (⋮) in the top right corner.\n"
        f"3️⃣ Select 'Share'.\n"
        f"4️⃣ Choose your payment app (Google Pay, PhonePe, Paytm, etc.).\n"
        f"5️⃣ Complete the payment. The amount will be filled automatically!\n\n"
        f"📸 <b>After payment, send a screenshot here to complete your order.</b>"
    )
    with open(qr_path, "rb") as qr:
        bot.send_photo(message.chat.id, qr, caption=caption, parse_mode="HTML", reply_markup=get_payment_keyboard())
    
    try:
        os.remove(qr_path)
    except Exception as e:
        logger.warning(f"Could not remove QR code file {qr_path}: {e}")
        pass
        
    push_state(message.chat.id, {'payment_sent': True})

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
    price_per_1000_user = service.get('price_with_margin', float(service['price']) * PROFIT_MARGIN)

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

if __name__ == '__main__':
    logger.info("=== BOT IS STARTING ===")
    try:
        if not os.path.exists('assets/payment_proofs'):
            os.makedirs('assets/payment_proofs')
        
        load_profit_margin()
        
        # This check ensures that if the API call fails, the bot will not start.
        if not load_services_from_api():
            logger.critical("Bot cannot start without services. Please check the AGENCY_API_KEY and the provider's status.")
            sys.exit("Could not load services from the agency API. Exiting.")
        
        logger.info("Bot polling started...")
        bot.infinity_polling()
    except Exception as e:
        logger.critical(f"An unrecoverable error occurred: {e}", exc_info=True)
    finally:
        logger.info("=== BOT STOPPED ===") 