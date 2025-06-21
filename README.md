# 🚀 AUTOSOCI Bot - Social Media Growth Platform

<div align="center">

![AUTOSOCI Bot](https://img.shields.io/badge/AUTOSOCI-Bot-brightgreen?style=for-the-badge&logo=telegram)
![Python](https://img.shields.io/badge/Python-3.8+-blue?style=for-the-badge&logo=python)
![Telegram](https://img.shields.io/badge/Telegram-Bot-0088cc?style=for-the-badge&logo=telegram)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

**Grow your social media presence with 100% organic, real engagement! 💚**

[Features](#-features) • [Platforms](#-supported-platforms) • [Setup](#-setup) • [Usage](#-usage) • [Admin Panel](#-admin-panel) • [Deployment](#-deployment)

</div>

---

## 🌟 Features

### ✨ **For Users**
- 🎯 **Multi-Platform Support**: Instagram, YouTube, Facebook, Twitter, TikTok, Telegram
- 💰 **Transparent Pricing**: See exact costs with profit margin display
- 🔒 **Secure Payments**: UPI QR code payments with screenshot verification
- 📊 **Real-time Tracking**: Order status updates and delivery notifications
- 🎨 **User-Friendly Interface**: Intuitive bot navigation with inline keyboards
- 📱 **Mobile Optimized**: Perfect experience on all devices

### ⚡ **For Admins**
- 🛠️ **Integrated Admin Panel**: Manage everything from within the bot
- 💹 **Dynamic Profit Margins**: Adjust pricing in real-time
- 📈 **Analytics Dashboard**: Track total orders and bot performance
- ✅ **Order Management**: Approve/reject orders with detailed notifications
- 🔄 **Broadcast Messages**: Send announcements to all users
- 📊 **Service Management**: Monitor and update service offerings

### 🎯 **Special Features**
- 🎬 **YouTube WatchTime Service**: Complete package with manager access support
- 📋 **Service Notes**: Detailed requirements and instructions for each service
- 🔗 **Manager Access Guide**: Built-in `/manageraccess` command with step-by-step instructions
- 🎨 **Attractive UI**: Professional design with emojis and formatting
- ⚡ **Fast Processing**: Quick order placement and status updates

---

## 📱 Supported Platforms

| Platform | Services Available |
|----------|-------------------|
| **Instagram** | Followers, Likes, Views, Comments, Shares |
| **YouTube** | Subscribers, Views, Watch Time, Comments, Likes |
| **Facebook** | Followers, Likes, Comments, Shares |
| **Twitter** | Followers, Likes, Retweets, Comments |
| **TikTok** | Followers, Likes, Views, Shares, Comments |
| **Telegram** | Members, Views, Reactions |

**Total Services**: 117+ services across all platforms

---

## 🛠️ Setup

### Prerequisites
- Python 3.8 or higher
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Agency API Key (for order processing)
- UPI ID (for payments)

### Installation

1. **Clone the Repository**
```bash
git clone https://github.com/yourusername/autosoci_bot.git
cd autosoci_bot
```

2. **Install Dependencies**
```bash
pip install -r requirements.txt
```

3. **Environment Setup**
Create a `.env` file in the root directory:
```env
BOT_TOKEN=your_telegram_bot_token_here
AGENCY_API_KEY=your_agency_api_key_here
UPI_ID=your_upi_id_here
ADMIN_ID=your_telegram_user_id_here
```

4. **Run the Bot**
```bash
python main.py
```

---

## 🚀 Usage

### For Users

1. **Start the Bot**: Send `/start` to begin
2. **Choose Platform**: Select your social media platform
3. **Select Category**: Choose the type of service you need
4. **Pick Service**: Select the specific service from the list
5. **Provide Link**: Share your content link
6. **Set Quantity**: Choose the amount (skipped for YouTube WatchTime)
7. **Review Order**: Check your order summary
8. **Make Payment**: Pay via UPI QR code
9. **Upload Proof**: Send payment screenshot
10. **Wait for Approval**: Admin will approve and process your order

### Special Commands

- `/start` - Start the bot and see main menu
- `/manageraccess` - Get detailed guide for YouTube Manager Access

---

## 👨‍💼 Admin Panel

### Access Admin Panel
- Send `/start` as an admin user
- Click "🔧 Admin Panel" button

### Admin Features

#### 📊 **Analytics**
- View total orders processed
- Monitor bot performance
- Track profit margins

#### 💰 **Profit Management**
- Set dynamic profit margins
- Real-time pricing adjustments
- Cost vs. profit tracking

#### 📋 **Order Management**
- Approve/reject orders
- View detailed order information
- Track order status

#### 📢 **Broadcasting**
- Send messages to all users
- Announce updates and offers
- Emergency notifications

---

## 🚀 Deployment

### Railway Deployment (Recommended)

1. **Connect to Railway**
   - Link your GitHub repository to Railway
   - Railway will auto-deploy on every push

2. **Environment Variables**
   Set these in Railway dashboard:
   ```
   BOT_TOKEN=your_bot_token
   AGENCY_API_KEY=your_api_key
   UPI_ID=your_upi_id
   ADMIN_ID=your_user_id
   ```

3. **Deploy**
   - Push changes to GitHub
   - Railway automatically deploys

### Other Platforms

#### Heroku
```bash
# Create Procfile
echo "worker: python main.py" > Procfile

# Deploy
heroku create your-bot-name
git push heroku main
```

#### VPS/Server
```bash
# Install dependencies
pip install -r requirements.txt

# Run with screen or systemd
screen -S autosoci_bot
python main.py
```

---

## 📁 Project Structure

```
autosoci_bot/
├── main.py                 # Main bot file
├── services.json          # Service configurations
├── requirements.txt       # Python dependencies
├── .env                  # Environment variables
├── assets/               # Static assets
│   ├── logo.jpg         # Bot logo
│   ├── upi_qr.png       # UPI QR template
│   └── payment_proofs/  # Payment screenshots
├── payment_proofs/       # Payment verification
├── bot.log              # Bot activity logs
└── admin.log            # Admin activity logs
```

---

## 🔧 Configuration

### Service Management
- Edit `services.json` to add/modify services
- Each service includes: platform, category, price, min/max quantities
- Special services like YouTube WatchTime have detailed notes

### Customization
- Modify `WELCOME_TEXT` in `main.py` for custom welcome messages
- Adjust profit margin calculations
- Customize payment instructions and UI

---

## 📊 Analytics & Monitoring

### Built-in Analytics
- Total orders processed
- Revenue tracking
- Service popularity
- User engagement metrics

### Logging
- Comprehensive logging system
- Separate logs for bot and admin activities
- Error tracking and debugging

---

## 🔒 Security Features

- ✅ **Payment Verification**: Screenshot-based payment proof
- ✅ **Admin Authentication**: Secure admin panel access
- ✅ **Input Validation**: Robust link and data validation
- ✅ **Error Handling**: Comprehensive error management
- ✅ **Rate Limiting**: Built-in protection against spam

---

## 🤝 Support

### For Users
- **WhatsApp Support**: [Join Support Group](https://chat.whatsapp.com/GvLbK18vIfELWWQgKYyoKw)
- **Bot Commands**: Use `/start` for help
- **Manager Access**: Use `/manageraccess` for YouTube setup

### For Developers
- **Issues**: Report bugs via GitHub Issues
- **Contributions**: Pull requests welcome
- **Documentation**: Check inline code comments

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Telegram Bot API**: For the excellent bot framework
- **Agency Partners**: For reliable service delivery
- **Community**: For feedback and support

---

<div align="center">

**Made with ❤️ by AUTOSOCI Team**

[![Telegram](https://img.shields.io/badge/Telegram-@AUTOSOCI_Bot-0088cc?style=flat-square&logo=telegram)](https://t.me/your_bot_username)
[![WhatsApp](https://img.shields.io/badge/WhatsApp-Support-25D366?style=flat-square&logo=whatsapp)](https://chat.whatsapp.com/GvLbK18vIfELWWQgKYyoKw)

</div> 