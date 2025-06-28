# Church SMS Broadcasting System

A Python-based SMS broadcasting system built with Twilio that allows church congregation members to send messages that are automatically shared with the entire community.

## 🏛️ System Overview

This system creates a unified SMS communication platform for churches where:
- Any congregation member can send a message to the church number
- The message is automatically broadcast to all groups
- Members are organized into different groups (families, youth, seniors, etc.)
- Administrators have special privileges for system management

## 🚀 Features

- **Multi-Group Broadcasting**: Organize members into different groups
- **Automatic Message Relay**: Messages sent to church number broadcast to all members
- **Admin Controls**: Special commands for administrators
- **Help System**: Built-in help commands
- **Webhook Integration**: Real-time message processing via Twilio webhooks
- **Group Management**: Easy addition and management of congregation members

## 📋 Prerequisites

- Python 3.7+
- Twilio Account (with A2P 10DLC registration for production use)
- Flask web framework
- Internet connection for webhook functionality

## 🛠️ Installation

1. **Clone or download the project files**

2. **Install required Python packages:**
```bash
pip install twilio flask
```

3. **Get Twilio credentials:**
   - Sign up at [Twilio.com](https://twilio.com)
   - Get your Account SID and Auth Token
   - Purchase a phone number (example: +14252875212)

4. **Configure Twilio webhook:**
```bash
twilio phone-numbers:update +14252875212 --sms-url="http://localhost:5000/webhook/sms"
```

## ⚙️ Configuration

### Update Twilio Credentials

Replace these placeholders in the code with your actual Twilio credentials:

```python
TWILIO_ACCOUNT_SID = "your_account_sid_here"  # Replace with real SID
TWILIO_AUTH_TOKEN = "your_auth_token_here"    # Replace with real Token
TWILIO_PHONE_NUMBER = "+14252875212"          # Your Twilio phone number
```

### Configure Your Congregation

Modify the `setup_your_congregation()` function to add your church members:

```python
def setup_your_congregation():
    # Pastor/Admin (can use admin commands)
    broadcast_sms.add_member_to_group("+14257729189", 1, "Pastor Mike", is_admin=True)
    
    # Group 1: Church Family
    broadcast_sms.add_member_to_group("+12065551001", 1, "John Smith")
    broadcast_sms.add_member_to_group("+12065551002", 1, "Mary Johnson")
    
    # Group 2: Youth Group
    broadcast_sms.add_member_to_group("+12065551003", 2, "Sarah Wilson")
    broadcast_sms.add_member_to_group("+12065551004", 2, "David Brown")
    
    # Group 3: Seniors
    broadcast_sms.add_member_to_group("+12065551005", 3, "Robert Davis")
    broadcast_sms.add_member_to_group("+12065551006", 3, "Linda Miller")
```

## 🏃‍♂️ Running the System

1. **Start the Flask application:**
```bash
python your_app_name.py
```

2. **You should see:**
```
✅ Added Pastor Mike (+14257729189) to Group 1
✅ Added John Smith (+12065551001) to Group 1
✅ Added Mary Johnson (+12065551002) to Group 1
...
🚀 Church SMS system initialized!
📱 Church number: +14252875212
👥 Total members: X
📊 Groups: Y
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://[your-ip]:5000
```

## 📱 How to Use

### For Congregation Members:

**Send a regular message:**
- Text anything to +14252875212
- Your message will be broadcast to all groups
- Example: "Prayer meeting tonight at 7pm!"

**Get help:**
- Text "HELP" to +14252875212
- Receive usage instructions

### For Administrators:

**View system status:**
- Text "STATUS" to get member count and group info

**All admin commands work the same as regular messages but provide additional system information**

## 🏗️ System Architecture

```
Congregation Member → Twilio Phone Number → Flask Webhook → Broadcasting Logic → All Members
```

1. **Member sends SMS** to church Twilio number
2. **Twilio receives message** and sends webhook to Flask app
3. **Flask app processes** the message and sender information
4. **Broadcasting system** sends message to all group members
5. **All members receive** the original message from the sender

## 🔧 Twilio A2P 10DLC Registration

For production use with multiple recipients, you must complete A2P 10DLC registration:

### Registration Details Used:
- **Campaign Type:** Mixed (church communications)
- **Description:** Church congregation communication system for sharing messages, announcements, and prayer requests among members
- **Sample Messages:**
  - "Welcome to our church family SMS! Send your messages to stay connected with our congregation. Sunday service is at 10am. God bless!"
  - "Prayer request from John: Please pray for my family during this difficult time. Thank you for your prayers and support."
  - "Church announcement: Potluck dinner this Saturday at 6pm in the fellowship hall. Bring a dish to share. See you there!"
  - "Reminder: Bible study tonight at 7pm in the sanctuary. We're studying Acts chapter 2. All are welcome to join us."
  - "Thank you for joining us today! Next week's service theme is 'Faith in Action'. Have a blessed week and see you Sunday."

### Opt-in Process:
- **Consent:** Members voluntarily text church number or request addition during services
- **Keywords:** JOIN, SUBSCRIBE, CHURCH
- **Opt-out:** Text STOP or contact church leadership

## 💰 Cost Estimates

Based on 50 congregation members:

- **SMS Cost:** $0.0075 per message
- **Phone Number:** ~$1/month
- **Example:** 25 messages/week = 100 messages/month × 50 people = 5,000 SMS = ~$38.50/month

## 🧪 Testing

### Trial Mode Testing:
1. **Verify phone numbers** in Twilio Console
2. **Add only verified numbers** to your congregation setup
3. **Test with verified members** (messages will include trial account prefix)
4. **Upgrade after A2P approval** for full functionality

### Testing Commands:
```python
# Add test function for direct SMS testing
def test_sms_directly():
    print("🧪 Testing SMS directly...")
    result = broadcast_sms.broadcast_to_all_groups("+14257729189", "Test message")
    print(f"Result: {result}")
```

## 🚨 Troubleshooting

### Common Issues:

**Messages not sending:**
- ✅ Check Twilio credentials are correct
- ✅ Verify A2P 10DLC registration status
- ✅ Ensure webhook URL is configured
- ✅ Check Python terminal for error messages

**Webhook not receiving messages:**
- ✅ Confirm Flask app is running
- ✅ Verify webhook URL in Twilio console
- ✅ Check firewall/network settings

**Members not receiving messages:**
- ✅ Verify phone number format (+1XXXXXXXXXX)
- ✅ Check if numbers are in trial verified list
- ✅ Confirm A2P registration is approved

## 📞 Support

- **Twilio Documentation:** [docs.twilio.com](https://docs.twilio.com)
- **A2P 10DLC Info:** [Twilio A2P 10DLC Guide](https://www.twilio.com/docs/sms/a2p-10dlc)
- **Flask Documentation:** [flask.palletsprojects.com](https://flask.palletsprojects.com)

## 📄 License

This project is created for church community use. Modify and distribute as needed for your congregation.

## 🙏 Acknowledgments

Built to strengthen church community communication and fellowship through modern technology while maintaining the personal touch of direct messaging between congregation members.