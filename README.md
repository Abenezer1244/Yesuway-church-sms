# YesuWay Church SMS Broadcasting System

> **A unified SMS communication platform that transforms multiple church groups into one seamless conversation for the entire congregation.**

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-2.3.3-green.svg)](https://flask.palletsprojects.com)
[![Twilio](https://img.shields.io/badge/Twilio-SMS%2FMMS-red.svg)](https://twilio.com)
[![License](https://img.shields.io/badge/License-Church%20Use-brightgreen.svg)](#license)

## 🏛️ Overview

The YesuWay Church SMS Broadcasting System is a production-ready communication platform that allows any congregation member to send a message to one number, which then broadcasts that message to the entire church community across multiple groups. This creates a unified conversation where everyone stays connected, regardless of which original group they belonged to.

### ✨ Key Benefits

- **🔗 Unified Communication**: Transforms 3+ separate SMS groups into one church-wide conversation
- **📱 Universal Access**: Works with any phone (iPhone, Android, flip phones)
- **📸 Rich Media Support**: Share photos, audio, and videos with the entire congregation
- **👑 Admin Controls**: Church leaders can manage members and view statistics via SMS
- **🤖 Auto-Management**: New members are automatically added when they text
- **☁️ 24/7 Operation**: Cloud-hosted for reliable, always-on service

---

## 🚀 Quick Start

### 1. **Text the Church Number**
Send any message to **+14252875212** and it broadcasts to everyone!

### 2. **Send Media**
Share photos, voice messages, or videos - everyone receives them.

### 3. **Get Help**
Text `HELP` to see all available commands.

### 4. **Admin Functions**
Church leaders can add members: `ADD +1234567890 John Smith TO 1`

---

## 📋 System Architecture

```
┌─────────────────┐    ┌──────────────┐    ┌─────────────────────┐
│   Church Member │───▶│ Twilio SMS   │───▶│  YesuWay System     │
│   +1234567890   │    │ +14252875212 │    │  (Cloud Hosted)     │
└─────────────────┘    └──────────────┘    └─────────────────────┘
                                                       │
                       ┌────────────────────────────────┼────────────────────────────────┐
                       ▼                                ▼                                ▼
            ┌─────────────────┐              ┌─────────────────┐              ┌─────────────────┐
            │ Congregation    │              │ Congregation    │              │ Congregation    │
            │ Group 1         │              │ Group 2         │              │ Group 3 (MMS)   │
            │ (SMS Members)   │              │ (SMS Members)   │              │ (SMS+MMS)       │
            └─────────────────┘              └─────────────────┘              └─────────────────┘
```

### Database Schema

The system uses SQLite with 6 core tables:

| Table | Purpose |
|-------|---------|
| `groups` | Stores the 3 congregation groups |
| `members` | All congregation members with contact info |
| `group_members` | Links members to their groups |
| `broadcast_messages` | Complete message history |
| `message_media` | Photos, audio, and video attachments |
| `delivery_log` | Delivery success/failure tracking |

---

## 🛠️ Installation & Deployment

### Prerequisites

- Python 3.9+
- Twilio Account with A2P 10DLC registration
- Cloud hosting account (Render.com recommended)
- GitHub account for code deployment

### Local Development Setup

1. **Clone the Repository**
```bash
git clone https://github.com/yourusername/yesuway-church-sms.git
cd yesuway-church-sms
```

2. **Install Dependencies**
```bash
pip install -r requirements.txt
```

3. **Environment Configuration**
Create a `.env` file:
```env
TWILIO_ACCOUNT_SID=your_account_sid_here
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=+14252875212
```

4. **Run Locally**
```bash
python app.py
```

### Production Deployment (Render.com)

1. **Fork this repository** to your GitHub account

2. **Create Render Account**
   - Sign up at [render.com](https://render.com)
   - Connect your GitHub account

3. **Deploy Web Service**
   - New → Web Service
   - Connect your forked repository
   - Configure:
     - **Runtime**: Python 3
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `python app.py`

4. **Set Environment Variables**
   ```
   TWILIO_ACCOUNT_SID = your_account_sid
   TWILIO_AUTH_TOKEN = your_auth_token  
   TWILIO_PHONE_NUMBER = +14252875212
   ```

5. **Configure Twilio Webhook**
   - Go to Twilio Console → Phone Numbers
   - Set webhook URL: `https://your-app.onrender.com/webhook/sms`
   - Method: POST

---

## 📱 User Guide

### For Congregation Members

#### **Sending Messages**
```
Text: "Prayer meeting tonight at 7pm!"
Result: Message goes to entire congregation
```

#### **Sharing Media**
- Send photos, voice recordings, or videos
- Everyone receives the actual media files
- Perfect for sharing service moments or announcements

#### **Getting Help**
```
Text: HELP
Response: Complete command guide
```

#### **Checking Groups**
```
Text: GROUPS
Response: Shows which groups you belong to
```

### For Church Administrators

#### **Adding New Members**
```
ADD +12065551234 John Smith TO 1
ADD +1234567890 Mary Johnson TO 2
ADD 206-555-9999 Robert Wilson TO 3
```

#### **Viewing Statistics**
```
Text: STATS
Response: 
📊 CONGREGATION STATISTICS

👥 Total Active Members: 25
📋 Group Breakdown:
  • Congregation Group 1: 12 members
  • Congregation Group 2: 8 members  
  • Congregation Group 3: 7 members
📈 Messages this week: 15
📎 Media messages: 6
```

#### **Recent Activity**
```
Text: RECENT
Response: Last 5 broadcast messages with details
```

---

## ⚙️ Configuration

### Current Group Setup

| Group ID | Name | Type | Description |
|----------|------|------|-------------|
| 1 | Congregation Group 1 | SMS | First congregation group |
| 2 | Congregation Group 2 | SMS | Second congregation group |
| 3 | Congregation Group 3 | MMS | Third group with media support |

### Adding Your Congregation

Edit the `setup_your_congregation()` function in `app.py`:

```python
def setup_your_congregation():
    # Add yourself as admin
    broadcast_sms.add_member_to_group("+14257729189", 1, "Pastor Mike", is_admin=True)
    
    # Group 1 Members
    broadcast_sms.add_member_to_group("+12065551001", 1, "John Smith")
    broadcast_sms.add_member_to_group("+12065551002", 1, "Mary Johnson")
    
    # Group 2 Members  
    broadcast_sms.add_member_to_group("+12065551003", 2, "David Wilson")
    broadcast_sms.add_member_to_group("+12065551004", 2, "Sarah Davis")
    
    # Group 3 Members (MMS)
    broadcast_sms.add_member_to_group("+12065551005", 3, "Robert Miller")
    broadcast_sms.add_member_to_group("+12065551006", 3, "Lisa Garcia")
```

---

## 🔧 Advanced Features

### Auto-Member Registration

When someone new texts your church number:
1. **Automatically added** to the system
2. **Assigned to Group 1** by default
3. **Can immediately participate** in conversations
4. **Admin can reassign** to different groups later

### Message Processing Flow

```python
# Incoming message processing
def handle_sms_with_media(self, from_phone, message_body, media_urls):
    # 1. Identify sender
    # 2. Check for commands (HELP, STATS, etc.)
    # 3. Process admin commands if applicable
    # 4. Broadcast to all groups if regular message
    # 5. Log everything for analytics
```

### Media Handling

The system supports:
- **📸 Images**: JPG, PNG, GIF
- **🎵 Audio**: MP3, WAV, voice recordings
- **🎥 Video**: MP4, MOV (up to Twilio limits)
- **📎 Documents**: PDF, TXT (basic support)

### Delivery Tracking

Every message is tracked with:
- Sender information
- Recipient delivery status
- Group-based analytics
- Failure reason logging
- Timestamp recording

---

## 📊 Analytics & Monitoring

### Built-in Analytics

The system provides comprehensive analytics:

#### **Message Volume Tracking**
- Total messages per week/month
- Media vs text message ratios
- Peak usage times
- Member participation rates

#### **Delivery Monitoring**
- Success/failure rates per recipient
- Group-based delivery statistics
- Failed delivery troubleshooting
- Performance metrics

#### **Member Analytics**
- Active vs inactive members
- Group distribution
- Admin activity tracking
- New member onboarding metrics

### Health Monitoring

- **Health Check Endpoint**: `https://your-app.onrender.com/`
- **Render Dashboard**: Built-in monitoring and logs
- **Twilio Console**: SMS delivery analytics
- **Database Logs**: Complete audit trail

---

## 🔐 Security & Privacy

### Security Features

- **🔐 Environment Variables**: No hardcoded credentials
- **🛡️ Input Validation**: Phone number sanitization
- **🚫 SQL Injection Protection**: Parameterized queries
- **📱 Rate Limiting**: Prevents spam (configurable)
- **👑 Admin Privileges**: Secure admin-only functions

### Privacy Considerations

- **📞 Phone Number Privacy**: Numbers stored securely
- **💬 Message Logging**: Complete audit trail maintained
- **🗑️ Data Retention**: Configurable message retention
- **👥 Member Consent**: Opt-in based system
- **🚪 Easy Opt-out**: Text "STOP" to unsubscribe

### GDPR & Compliance

- Member data stored with consent
- Easy data deletion upon request
- Audit trail for compliance
- Secure data transmission via HTTPS

---

## 💰 Cost Analysis

### Twilio Costs (Production)

| Component | Cost | Notes |
|-----------|------|-------|
| Phone Number | $1.00/month | One-time setup |
| SMS Messages | $0.0075 each | Per message sent |
| MMS Messages | $0.02 each | Photos/audio/video |

### Example Costs for YesuWay

**Current Setup**: 3 members, testing phase
- **Estimated**: $5-10/month

**50 Members, 25 messages/week**:
- Messages: 25 × 4 weeks × 50 people = 5,000 SMS
- Cost: 5,000 × $0.0075 = $37.50/month
- Total: ~$38.50/month

**100 Members, 20 messages/week**:
- Messages: 20 × 4 weeks × 100 people = 8,000 SMS  
- Cost: 8,000 × $0.0075 = $60/month
- Total: ~$61/month

### Hosting Costs

- **Render.com**: FREE tier (perfect for churches)
- **Alternative**: Heroku ($7/month for hobby tier)

---

## 🧪 Testing

### Testing Commands

Text these to your church number to test functionality:

#### **Basic Commands**
```
HELP        # Shows all available commands
STATS       # Displays congregation statistics  
GROUPS      # Shows your group memberships
```

#### **Admin Commands** (Admin only)
```
ADD +1234567890 Test User TO 1    # Adds new member
RECENT                            # Shows recent broadcasts
```

#### **Media Testing**
- Send a photo with text
- Send a voice recording
- Send a video message

### Local Testing

1. **Install ngrok** for webhook testing:
```bash
ngrok http 5000
```

2. **Update Twilio webhook** to ngrok URL temporarily

3. **Test all functions** before production deployment

### Production Testing

1. **Verify webhook** is receiving messages
2. **Test with multiple members** from different groups
3. **Confirm media delivery** across all recipients
4. **Validate admin commands** work properly

---

## 🚨 Troubleshooting

### Common Issues

#### **Messages Not Sending**
```bash
# Check Render logs
https://dashboard.render.com/your-app/logs

# Verify Twilio webhook
curl -X POST https://your-app.onrender.com/webhook/sms \
  -d "From=+1234567890&Body=test"
```

#### **Media Not Delivering**
1. **Verify A2P 10DLC** includes MMS permissions
2. **Check phone number** supports MMS in Twilio Console
3. **Test MMS** directly from Twilio Console

#### **Webhook Failures**
- Ensure webhook URL is correct
- Verify app is running (check health endpoint)
- Check Render deployment status

### Debug Mode

Enable debug logging in production:
```python
# In app.py, temporarily set:
app.run(host='0.0.0.0', port=port, debug=True)
```

### Error Logs

Check these sources for troubleshooting:
- **Render Dashboard**: Application logs
- **Twilio Console**: SMS delivery logs  
- **Database**: Check church_broadcast.db
- **Browser**: Test health endpoint

---

## 🔄 Maintenance

### Regular Maintenance Tasks

#### **Weekly**
- Monitor message delivery rates
- Check for new member registrations
- Review error logs

#### **Monthly**  
- Analyze congregation statistics
- Update member information
- Review Twilio usage and costs

#### **Quarterly**
- Database backup and cleanup
- Security review and updates
- Feature enhancement planning

### Updating the System

```bash
# Make changes to code
git add .
git commit -m "Update message formatting"
git push origin main

# Render auto-deploys from GitHub
# No manual deployment needed
```

### Database Backup

```bash
# Local backup
cp church_broadcast.db church_backup_$(date +%Y%m%d).db

# Render backup (download via dashboard)
# Or implement automated backup script
```

---

## 🤝 Contributing

### For Church Tech Teams

1. **Fork the repository**
2. **Create feature branch** (`git checkout -b feature/new-command`)
3. **Make changes** and test thoroughly
4. **Commit changes** (`git commit -m 'Add new feature'`)
5. **Push to branch** (`git push origin feature/new-command`)
6. **Create Pull Request**

### Customization Ideas

- **Custom commands** for your church's needs
- **Event scheduling** integration
- **Prayer request** management
- **Attendance tracking** via SMS
- **Offering reminders** and tracking

---

## 📞 Support

### Documentation
- **Twilio SMS Guide**: [docs.twilio.com/sms](https://docs.twilio.com/sms)
- **Flask Documentation**: [flask.palletsprojects.com](https://flask.palletsprojects.com)
- **Render Deployment**: [render.com/docs](https://render.com/docs)

### Getting Help

For technical issues:
1. **Check logs** in Render dashboard
2. **Review Twilio Console** for delivery issues
3. **Test webhook** manually
4. **Contact church tech team** for assistance

### Feature Requests

Have ideas for new features? Consider:
- **Automated service reminders**
- **Bible verse of the day**
- **Prayer request management**
- **Event RSVP tracking**
- **Volunteer coordination**

---

## 📄 License

This project is created specifically for church community use. Feel free to modify and distribute for your congregation's needs.

### Usage Terms
- ✅ **Church and religious organization use**
- ✅ **Modification for your specific needs**
- ✅ **Sharing with other churches**
- ❌ **Commercial resale or licensing**

---

## 🙏 Acknowledgments

**Built to strengthen church community communication and fellowship through modern technology while maintaining the personal touch of direct messaging between congregation members.**

### Technologies Used
- **Python 3.9+** - Core application language
- **Flask** - Web framework for webhook handling
- **Twilio** - SMS/MMS messaging service
- **SQLite** - Database for member and message storage
- **Render.com** - Cloud hosting platform

### Special Thanks
- **YesuWay Church Community** - For inspiring this unified communication solution
- **Twilio Developer Community** - For excellent SMS/MMS documentation
- **Open Source Community** - For the foundational technologies

---

## 📈 Roadmap

### Upcoming Features
- [ ] **Scheduled Messages** - Send announcements at specific times
- [ ] **Prayer Request Management** - Dedicated prayer tracking
- [ ] **Event RSVP System** - Track attendance for church events
- [ ] **Multi-language Support** - Serve diverse congregations
- [ ] **Voice Message Transcription** - Convert audio to text
- [ ] **Integration APIs** - Connect with church management systems

### Long-term Vision
- **Multi-church deployment** - Serve multiple congregations
- **Advanced analytics** - Detailed engagement metrics
- **Mobile app companion** - Enhanced user experience
- **AI-powered features** - Smart message categorization

---

**🏛️ May this system strengthen the bonds of fellowship in your church community and help spread God's love through enhanced communication! 🙏**