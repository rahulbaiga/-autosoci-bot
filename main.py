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

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_IDS')
AGENCY_API_KEY = os.getenv('AGENCY_API_KEY')
UPI_ID = os.getenv('UPI_ID')

if not BOT_TOKEN or not ADMIN_ID or not AGENCY_API_KEY or not UPI_ID:
    logger.error('Missing required environment variables. Please check your .env file.')
    sys.exit(1)

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

def load_services():
    """Loads services from JSON and assigns a unique ID to each for callbacks."""
    global loaded_services, services_by_id
    with open('services.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        service_id_counter = 1
        platforms = {}
        for service_data in data:
            platform_name = service_data['platform']
            category_name = service_data['category']

            if platform_name not in platforms:
                platforms[platform_name] = {}
            if category_name not in platforms[platform_name]:
                platforms[platform_name][category_name] = []

            # Assign a unique ID for button callbacks
            service_data['id'] = service_id_counter
            platforms[platform_name][category_name].append(service_data)
            services_by_id[service_id_counter] = service_data
            service_id_counter += 1
        loaded_services = platforms
        logger.info(f"Successfully loaded and indexed {len(services_by_id)} services.")

def find_service_by_id(service_id):
    """Finds a service in the loaded dictionary by its unique ID."""
    return services_by_id.get(service_id)

# Load services.json for platforms
with open('services.json', 'r', encoding='utf-8') as f:
    SERVICES = json.load(f)

# Extract unique platforms
PLATFORMS = sorted(set(service['platform'] for service in SERVICES))
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
    markup.add(types.InlineKeyboardButton('⬅️ Back to Platforms', callback_data="back_to_platform"))
    return markup

def get_service_keyboard(platform, category):
    services = loaded_services.get(platform, {}).get(category, [])
    markup = types.InlineKeyboardMarkup(row_width=1)
    for service in services:
        # Calculate price with profit margin for user display
        price_per_1000 = float(service['price']) * PROFIT_MARGIN
        btn_text = f"{service['service']} (₹{price_per_1000:.2f}/1k)"
        # Use the unique service ID in the callback_data
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"service_{service['id']}"))
    markup.add(types.InlineKeyboardButton('⬅️ Back to Categories', callback_data=f"back_to_category_{platform}"))
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
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_service"))
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
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_link"))
    return markup

def get_summary_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton('✅ Confirm Order', callback_data="confirm_order"))
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_quantity"))
    return markup

def get_payment_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_summary"))
    return markup

def get_payment_proof_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton('⬅️ Back', callback_data="back_to_payment"))
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
    bot.send_message(
        message.chat.id,
        WELCOME_TEXT,
        parse_mode='HTML',
        reply_markup=get_platform_keyboard()
    )
    user_state[message.chat.id] = {'step': 'platform'}

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

# --- NEW CALLBACK HANDLERS FOR INLINE BUTTONS ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('platform_') or call.data == 'back_to_platform')
def handle_platform_callback(call):
    logger.info(f"User {call.message.chat.id} selected: {call.data}")
    bot.answer_callback_query(call.id)
    if call.data == 'back_to_platform':
        # This case is handled by the category handler, but good to have
        user_state[call.message.chat.id]['step'] = 'platform'
        bot.edit_message_text("👋 <b>Welcome to AUTOSOCI Bot!</b>", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_platform_keyboard())
        return

    platform = call.data.split('_', 1)[1]
    user_state[call.message.chat.id] = {'step': 'category', 'platform': platform}
    bot.edit_message_text(f"You selected <b>{platform}</b>. Now choose a category:", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_category_keyboard(platform))


@bot.callback_query_handler(func=lambda call: call.data.startswith('category_') or call.data.startswith('back_to_category_'))
def handle_category_callback(call):
    logger.info(f"User {call.message.chat.id} selected: {call.data}")
    bot.answer_callback_query(call.id)
    state = user_state.get(call.message.chat.id, {})
    
    if call.data.startswith('back_to_category_'):
        user_state[call.message.chat.id]['step'] = 'platform'
        bot.edit_message_text("👋 <b>Welcome to AUTOSOCI Bot!</b>", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_platform_keyboard())
        return

    _, platform, category = call.data.split('_', 2)
    state['category'] = category
    state['step'] = 'service'
    bot.edit_message_text(f"You selected <b>{category}</b>. Now choose a service:", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_service_keyboard(platform, category))


@bot.callback_query_handler(func=lambda call: call.data.startswith('service_'))
def handle_service_selection(call):
    """Handles the user's service choice using the unique service ID."""
    logger.info(f"User {call.message.chat.id} selected: {call.data}")
    try:
        service_id = int(call.data.split('_')[1])
        service = find_service_by_id(service_id)
        if not service:
            bot.answer_callback_query(call.id, "❌ Error: Service not found. It might be outdated.", show_alert=True)
            return

        state = user_state.get(call.message.chat.id, {})
        state['service_id'] = service_id
        state['step'] = 'link'
        user_state[call.message.chat.id] = state

        # Check if service has detailed notes
        if 'notes' in service:
            text = f"✅ <b>You selected: {service['service']}</b>\n\n{service['notes']}"
            markup = get_link_keyboard()
            # Add manager access button for YouTube WatchTime
            if service['platform'] == 'YouTube' and 'WatchTime' in service['service']:
                markup.add(types.InlineKeyboardButton('ℹ️ What is Manager Access?', callback_data='manageraccess_info'))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
            # PROMPT USER TO SEND LINK
            prompt = get_link_prompt(service['platform'], service['service'])
            bot.send_message(call.message.chat.id, f"🔗 <b>Next Step:</b> {prompt}", parse_mode='HTML')
            return
        else:
            # Standard service selection
            prompt = get_link_prompt(service['platform'], service['service'])
            bot.edit_message_text(f"✅ You selected <b>{service['service']}</b>!\n\n{prompt}", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_link_keyboard())
    except (ValueError, IndexError) as e:
        logger.error(f"Error handling service selection for call data '{call.data}': {e}")
        bot.answer_callback_query(call.id, "❌ An unexpected error occurred.", show_alert=True)

@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get('step') == 'link')
def handle_link(message):
    logger.info(f"User {message.chat.id} submitted link: {message.text}")
    state = user_state.get(message.chat.id, {})
    
    # Basic link validation
    if not message.text.startswith(('http://', 'https://')):
        bot.reply_to(message, "❌ That doesn't look like a valid link. Please send a valid link starting with http:// or https://")
        return

    state['link'] = message.text
    
    # Check if this is YouTube WatchTime service - skip quantity selection
    service = find_service_by_id(state.get('service_id'))
    if service and service['platform'] == 'YouTube' and 'WatchTime' in service['service']:
        # For YouTube WatchTime, use fixed quantity of 1000 and go directly to summary
        state['quantity'] = 1000
        state['step'] = 'summary'
        user_state[message.chat.id] = state
        
        # Show order summary directly
        show_order_summary(message.chat.id)
        return
    
    # For all other services, proceed with quantity selection
    state['step'] = 'quantity'
    bot.send_message(message.chat.id, "✅ Link received! Now, how much engagement would you like?", reply_markup=get_quantity_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith('quantity_') or call.data == 'custom_quantity' or call.data == 'back_to_link')
def handle_quantity_callback(call):
    logger.info(f"User {call.message.chat.id} selected: {call.data}")
    bot.answer_callback_query(call.id)
    state = user_state.get(call.message.chat.id, {})

    if call.data == 'back_to_link':
        state['step'] = 'link'
        prompt = get_link_prompt(state['service']['platform'], state['service']['service'])
        bot.edit_message_text(f"✅ You selected <b>{state['service']['service']}</b>!\n\n{prompt}", call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_link_keyboard())
        return

    if call.data == 'custom_quantity':
        state['step'] = 'awaiting_custom_quantity'
        bot.send_message(call.message.chat.id, "💡 Please enter the desired quantity (e.g., 1000):")
        return

    quantity = int(call.data.split('_')[1])
    process_quantity(call.message, quantity)

@bot.callback_query_handler(func=lambda call: call.data == 'confirm_order' or call.data == 'back_to_quantity')
def handle_summary_callback(call):
    logger.info(f"User {call.message.chat.id} selected: {call.data}")
    bot.answer_callback_query(call.id)
    
    if call.data == 'back_to_quantity':
        user_state[call.message.chat.id]['step'] = 'quantity'
        bot.edit_message_text("🔙 Back to quantity selection:", call.message.chat.id, call.message.message_id, reply_markup=get_quantity_keyboard())
        return
    
    if call.data == 'confirm_order':
        user_state[call.message.chat.id]['step'] = 'payment'
        congrats_msg = (
            "🎉 <b>Congratulations!</b> 🎉\n\n"
            "Thank you for choosing <b>AUTOSOCI</b> to boost your social presence! 🚀\n"
            "You're just one step away from growing your account with 100% organic results. 💚\n\n"
            "Let's complete your order and get you started on your journey to success! 🌟"
        )
        bot.send_message(call.message.chat.id, congrats_msg, parse_mode='HTML')
        send_payment_instructions(call.message)

@bot.message_handler(content_types=['photo'], func=lambda m: user_state.get(m.chat.id, {}).get('step') == 'payment')
def handle_payment_proof(message):
    logger.info(f"User {message.chat.id} uploaded payment proof.")
    state = user_state.get(message.chat.id, {})
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

    state['step'] = 'pending_approval'
    user_state[message.chat.id] = state

@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get('step') == 'payment' and m.content_type != 'photo')
def prompt_payment_proof(message):
    if message.text == '⬅️ Back':
        user_state[message.chat.id]['step'] = 'summary'
        show_order_summary(message.chat.id)
        return
    bot.send_message(message.chat.id, "📸 Please upload your payment screenshot to complete your order.", reply_markup=get_payment_proof_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith('approve_') or call.data.startswith('reject_'))
def handle_admin_approval(call):
    action, user_id, order_id = call.data.split('_', 2)
    user_id = int(user_id)
    state = user_state.get(user_id)
    if not state:
        bot.answer_callback_query(call.id, "Order not found or already processed.")
        return
    if action == 'approve':
        bot.answer_callback_query(call.id, "Order approved!")
        
        service = find_service_by_id(state['service_id'])
        service_id = service.get('api_service_id')
        
        if not service_id:
            logger.error(f"Order approval failed for user {user_id}: 'api_service_id' missing for service '{service.get('service')}'")
            bot.send_message(user_id, "❌ <b>There was a configuration error with this service. Please contact support.</b>", parse_mode='HTML')
            bot.send_message(call.message.chat.id, f"<b>APPROVAL FAILED:</b> Service '{service.get('service')}' is missing its `api_service_id` in services.json.", parse_mode='HTML')
            return

        link = state['link']
        quantity = state['quantity']
        
        logger.info(f"Attempting to place order for user {user_id} with service_id {service_id}")
        order_id = place_agency_order(service_id, link, quantity)
        
        if order_id:
            state['agency_order_id'] = order_id
            bot.send_message(user_id, f"✅ <b>Your payment has been approved!</b>\nYour order is now being processed.\nOrder ID: <code>{order_id}</code>\nThank you for your trust!", parse_mode='HTML')
            state['step'] = 'processing'
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
    
    state = user_state.get(call.message.chat.id, {})
    state['step'] = 'awaiting_margin'
    user_state[call.message.chat.id] = state
    
    bot.answer_callback_query(call.id)
    bot.edit_message_text(
        f"Please enter the new profit margin <b>percentage</b>.\n\n"
        f"For example, for a 40% margin, enter `40`.\n"
        f"The current margin is `{(PROFIT_MARGIN - 1) * 100:.0f}%`.",
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )

@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get('step') == 'awaiting_margin')
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
        
        # Reset state and show admin panel
        user_state.pop(message.chat.id, None)
        bot.send_message(message.chat.id, "Returning to the admin panel.", reply_markup=get_admin_keyboard())

    except (ValueError, TypeError):
        bot.reply_to(message, "❌ Invalid input. Please enter a number (e.g., 40).")

def show_order_summary(chat_id):
    state = user_state.get(chat_id, {})
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
    if 'last_message_id' in state:
        bot.edit_message_text(summary_text, chat_id, state['last_message_id'], parse_mode='HTML', reply_markup=get_summary_keyboard())
    else:
        sent_message = bot.send_message(chat_id, summary_text, parse_mode='HTML', reply_markup=get_summary_keyboard())
        state['last_message_id'] = sent_message.message_id
        user_state[chat_id] = state

def process_quantity(message, quantity):
    state = user_state.get(message.chat.id, {})
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

    state['quantity'] = quantity
    state['step'] = 'summary'
    user_state[message.chat.id] = state

    # Calculate final amount for the summary
    final_amount = (float(service['price']) / 1000) * quantity * PROFIT_MARGIN
    
    summary_text = (
        f"<b>📝 Order Summary</b>\n\n"
        f"🟢 Platform: {service['platform']}\n"
        f"🟢 Service: {service['service']}\n"
        f"🟢 Link: {state['link']}\n"
        f"🟢 Quantity: {quantity}\n"
        f"💰 <b>Total Amount: ₹{final_amount:.2f}</b>"
    )
    
    # Store the message ID so we can edit it later
    sent_message = bot.send_message(message.chat.id, summary_text, parse_mode='HTML', reply_markup=get_summary_keyboard())
    state['last_message_id'] = sent_message.message_id
    user_state[message.chat.id] = state

def send_payment_instructions(message):
    state = user_state.get(message.chat.id, {})
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
        
    state['payment_sent'] = True

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_summary')
def handle_back_to_summary(call):
    logger.info(f"User {call.message.chat.id} going back to summary")
    bot.answer_callback_query(call.id)
    user_state[call.message.chat.id]['step'] = 'summary'
    show_order_summary(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_payment')
def handle_back_to_payment(call):
    logger.info(f"User {call.message.chat.id} going back to payment")
    bot.answer_callback_query(call.id)
    user_state[call.message.chat.id]['step'] = 'payment'
    send_payment_instructions(call.message)

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

if __name__ == '__main__':
    logger.info("=== BOT IS STARTING ===")
    try:
        if not os.path.exists('assets/payment_proofs'):
            os.makedirs('assets/payment_proofs')
        
        load_profit_margin()
        load_services() # Load services into memory
        
        logger.info("Bot polling started...")
        bot.infinity_polling()
    except Exception as e:
        logger.critical(f"An unrecoverable error occurred: {e}", exc_info=True)
    finally:
        logger.info("=== BOT STOPPED ===") 