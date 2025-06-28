from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import sqlite3
import re
from datetime import datetime
import os

# Twilio Configuration - Using Environment Variables
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')

app = Flask(__name__)

class MultiGroupBroadcastSMS:
    def __init__(self):
        self.client = None
        if TWILIO_ACCOUNT_SID:
            self.client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        self.init_database()
        
    def init_database(self):
        """Initialize database for multi-group broadcast system"""
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        
        # Groups table - your 3 existing groups
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Members table - everyone from all your groups
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                is_admin BOOLEAN DEFAULT FALSE,
                active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Group membership - tracks which group each member came from originally
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS group_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                member_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES groups (id),
                FOREIGN KEY (member_id) REFERENCES members (id),
                UNIQUE(group_id, member_id)
            )
        ''')
        
        # Broadcast messages - all messages that go to everyone
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS broadcast_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_phone TEXT NOT NULL,
                from_name TEXT NOT NULL,
                message_text TEXT NOT NULL,
                message_type TEXT DEFAULT 'broadcast',
                has_media BOOLEAN DEFAULT FALSE,
                media_count INTEGER DEFAULT 0,
                thread_id INTEGER NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Media attachments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS message_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                media_url TEXT NOT NULL,
                media_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (message_id) REFERENCES broadcast_messages (id)
            )
        ''')
        
        # Delivery tracking - track delivery to all 3 groups
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS delivery_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                to_phone TEXT NOT NULL,
                to_group_id INTEGER NOT NULL,
                delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'sent',
                FOREIGN KEY (message_id) REFERENCES broadcast_messages (id),
                FOREIGN KEY (to_group_id) REFERENCES groups (id)
            )
        ''')
        
        # Create your 3 congregation groups if they don't exist
        cursor.execute("SELECT COUNT(*) FROM groups")
        if cursor.fetchone()[0] == 0:
            groups = [
                ("Congregation Group 1", "First congregation group"),
                ("Congregation Group 2", "Second congregation group"), 
                ("Congregation Group 3", "Third congregation group (MMS)")
            ]
            cursor.executemany("INSERT INTO groups (name, description) VALUES (?, ?)", groups)
        
        conn.commit()
        conn.close()
        print("🏛️ Multi-Group Broadcast Database initialized!")
    
    def clean_phone_number(self, phone):
        """Clean and format phone number"""
        digits = re.sub(r'\D', '', phone)
        if len(digits) == 10:
            return f"+1{digits}"
        elif len(digits) == 11 and digits.startswith('1'):
            return f"+{digits}"
        return phone
    
    def add_member_to_group(self, phone_number, group_id, name, is_admin=False):
        """Add a member to a specific group"""
        phone_number = self.clean_phone_number(phone_number)
        
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        
        # Insert or update member
        cursor.execute('''
            INSERT OR REPLACE INTO members (phone_number, name, is_admin, active) 
            VALUES (?, ?, ?, 1)
        ''', (phone_number, name, is_admin))
        
        # Get member ID
        cursor.execute("SELECT id FROM members WHERE phone_number = ?", (phone_number,))
        member_id = cursor.fetchone()[0]
        
        # Add to group
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO group_members (group_id, member_id) 
                VALUES (?, ?)
            ''', (group_id, member_id))
            conn.commit()
            print(f"✅ Added {name} ({phone_number}) to Group {group_id}")
        except Exception as e:
            print(f"❌ Error adding member: {e}")
        finally:
            conn.close()
    
    def get_all_members_across_groups(self, exclude_phone=None):
        """Get ALL members from ALL groups (no duplicates)"""
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        
        query = '''
            SELECT DISTINCT m.phone_number, m.name, m.is_admin
            FROM members m
            JOIN group_members gm ON m.id = gm.member_id
            WHERE m.active = 1
        '''
        params = []
        
        if exclude_phone:
            exclude_phone = self.clean_phone_number(exclude_phone)
            query += " AND m.phone_number != ?"
            params.append(exclude_phone)
        
        cursor.execute(query, params)
        members = [{"phone": row[0], "name": row[1], "is_admin": bool(row[2])} for row in cursor.fetchall()]
        conn.close()
        return members
    
    def get_member_groups(self, phone_number):
        """Get which groups a member belongs to"""
        phone_number = self.clean_phone_number(phone_number)
        
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT g.id, g.name 
            FROM groups g
            JOIN group_members gm ON g.id = gm.group_id
            JOIN members m ON gm.member_id = m.id
            WHERE m.phone_number = ?
        ''', (phone_number,))
        
        groups = [{"id": row[0], "name": row[1]} for row in cursor.fetchall()]
        conn.close()
        return groups
    
    def is_admin(self, phone_number):
        """Check if user is admin"""
        phone_number = self.clean_phone_number(phone_number)
        
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        cursor.execute("SELECT is_admin FROM members WHERE phone_number = ?", (phone_number,))
        result = cursor.fetchone()
        conn.close()
        
        return bool(result[0]) if result else False
    
    def get_member_info(self, phone_number):
        """Get member information"""
        phone_number = self.clean_phone_number(phone_number)
        
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        cursor.execute("SELECT name, is_admin FROM members WHERE phone_number = ?", (phone_number,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {"name": result[0], "is_admin": bool(result[1])}
        else:
            # Auto-create new member
            name = f"Member {phone_number[-4:]}"
            self.add_member_to_group(phone_number, 1, name)  # Add to Group 1 by default
            return {"name": name, "is_admin": False}
    
    def supports_mms(self, phone_number):
        """Check if a member can receive MMS - now everyone can!"""
        # Since your Twilio number and campaign support MMS,
        # and most modern phones support MMS, let's enable it for everyone
        return True
    
    def broadcast_with_media(self, from_phone, message_text, media_urls, message_type='broadcast'):
        """Send message WITH media to EVERYONE across ALL 3 groups"""
        sender = self.get_member_info(from_phone)
        all_recipients = self.get_all_members_across_groups(exclude_phone=from_phone)
        
        if not all_recipients:
            return "No congregation members found to send to."
        
        # Store the broadcast message
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO broadcast_messages (from_phone, from_name, message_text, message_type, has_media, media_count) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (from_phone, sender['name'], message_text, message_type, bool(media_urls), len(media_urls)))
        message_id = cursor.lastrowid
        
        # Store media URLs
        for media in media_urls:
            cursor.execute('''
                INSERT INTO message_media (message_id, media_url, media_type) 
                VALUES (?, ?, ?)
            ''', (message_id, media['url'], media['type']))
        
        conn.commit()
        conn.close()
        
        # Format message for recipients
        media_text = ""
        if media_urls:
            media_count = len(media_urls)
            media_types = [media['type'].split('/')[0] for media in media_urls]
            if 'image' in media_types:
                media_text = f" 📸 [{media_count} photo(s)]"
            elif 'audio' in media_types:
                media_text = f" 🎵 [{media_count} audio file(s)]"
            elif 'video' in media_types:
                media_text = f" 🎥 [{media_count} video(s)]"
            else:
                media_text = f" 📎 [{media_count} file(s)]"
        
        if message_type == 'reaction':
            formatted_message = f"💭 {sender['name']} responded:\n{message_text}{media_text}"
        else:
            formatted_message = f"💬 {sender['name']}:\n{message_text}{media_text}"
        
        # Send to ALL members across ALL groups
        sent_count = 0
        failed_count = 0
        mms_sent = 0
        sms_sent = 0
        group_breakdown = {}
        
        for recipient in all_recipients:
            # Get recipient's groups for tracking
            recipient_groups = self.get_member_groups(recipient['phone'])
            recipient_supports_mms = self.supports_mms(recipient['phone'])
            
            try:
                if media_urls:
                    # Send MMS with media to everyone
                    message_obj = self.client.messages.create(
                        body=formatted_message,
                        from_=TWILIO_PHONE_NUMBER,
                        to=recipient['phone'],
                        media_url=[media['url'] for media in media_urls]
                    )
                    mms_sent += 1
                    print(f"📱 MMS sent to {recipient['phone']}: {message_obj.sid}")
                else:
                    # Send SMS only (no media)
                    message_obj = self.client.messages.create(
                        body=formatted_message,
                        from_=TWILIO_PHONE_NUMBER,
                        to=recipient['phone']
                    )
                    sms_sent += 1
                    print(f"📱 SMS sent to {recipient['phone']}: {message_obj.sid}")
                
                sent_count += 1
                
                # Log delivery for each group they're in
                for group in recipient_groups:
                    self.log_delivery(message_id, recipient['phone'], group['id'], 'sent')
                    group_breakdown[group['name']] = group_breakdown.get(group['name'], 0) + 1
                    
            except Exception as e:
                failed_count += 1
                print(f"❌ Failed to send to {recipient['phone']}: {e}")
                for group in recipient_groups:
                    self.log_delivery(message_id, recipient['phone'], group['id'], 'failed')
        
        # Create simple confirmation (only for admin)
        if self.is_admin(from_phone):
            confirmation = f"✅ Sent to {sent_count} members"
            if failed_count > 0:
                confirmation += f" ({failed_count} failed)"
            return confirmation
        else:
            # For regular members, no confirmation message
            return None
    
    def log_delivery(self, message_id, to_phone, to_group_id, status):
        """Log message delivery per group"""
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO delivery_log (message_id, to_phone, to_group_id, status) 
            VALUES (?, ?, ?, ?)
        ''', (message_id, to_phone, to_group_id, status))
        conn.commit()
        conn.close()
    
    def send_sms(self, to_phone, message):
        """Send SMS via Twilio"""
        if not self.client:
            print(f"📱 [TEST MODE] Would send to {to_phone}: {message}")
            return True
        
        try:
            message_obj = self.client.messages.create(
                body=message,
                from_=TWILIO_PHONE_NUMBER,
                to=to_phone
            )
            print(f"📱 SMS sent to {to_phone}: {message_obj.sid}")
            return True
        except Exception as e:
            print(f"❌ Failed to send SMS to {to_phone}: {e}")
            return False
    
    def get_congregation_stats(self):
        """Get statistics about all groups"""
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        
        # Total members across all groups
        cursor.execute("SELECT COUNT(DISTINCT m.id) FROM members m JOIN group_members gm ON m.id = gm.member_id WHERE m.active = 1")
        total_members = cursor.fetchone()[0]
        
        # Members per group
        cursor.execute('''
            SELECT g.name, COUNT(DISTINCT m.id) as member_count
            FROM groups g
            LEFT JOIN group_members gm ON g.id = gm.group_id
            LEFT JOIN members m ON gm.member_id = m.id AND m.active = 1
            GROUP BY g.id, g.name
        ''')
        group_stats = cursor.fetchall()
        
        # Recent message count
        cursor.execute("SELECT COUNT(*) FROM broadcast_messages WHERE sent_at > datetime('now', '-7 days')")
        recent_messages = cursor.fetchone()[0]
        
        # Media message count
        cursor.execute("SELECT COUNT(*) FROM broadcast_messages WHERE has_media = 1 AND sent_at > datetime('now', '-7 days')")
        recent_media = cursor.fetchone()[0]
        
        conn.close()
        
        stats = f"📊 CONGREGATION STATISTICS\n\n"
        stats += f"👥 Total Active Members: {total_members}\n\n"
        stats += f"📋 Group Breakdown:\n"
        for group_name, count in group_stats:
            stats += f"  • {group_name}: {count} members\n"
        stats += f"\n📈 Messages this week: {recent_messages}"
        stats += f"\n📎 Media messages: {recent_media}"
        
        return stats
    
    def handle_sms_with_media(self, from_phone, message_body, media_urls):
        """Main SMS handler for multi-group broadcasting with media support"""
        from_phone = self.clean_phone_number(from_phone)
        message_body = message_body.strip() if message_body else ""
        
        print(f"📨 Processing broadcast: {from_phone} -> {message_body}")
        if media_urls:
            print(f"📎 Media received: {len(media_urls)} files")
            for media in media_urls:
                print(f"   - {media['type']}: {media['url']}")
        
        # Ensure member exists (auto-add to Group 1 if new)
        member = self.get_member_info(from_phone)
        
        # DEFAULT: Broadcast message with media to ALL groups
        return self.broadcast_with_media(from_phone, message_body, media_urls, 'broadcast')

# Initialize the system
broadcast_sms = MultiGroupBroadcastSMS()

def setup_your_congregation():
    """Setup your 3 existing groups with real members"""
    print("🔧 Setting up your 3 congregation groups...")
    
    # Add yourself as admin
    broadcast_sms.add_member_to_group("+14257729189", 1, "Mike", is_admin=True)
    
    # GROUP 1 MEMBERS (SMS Group 1) - REPLACE WITH REAL NUMBERS
    print("📱 Adding Group 1 members...")
    broadcast_sms.add_member_to_group("+12068001141", 1, "Mike")
    
    # GROUP 2 MEMBERS (SMS Group 2) - REPLACE WITH REAL NUMBERS  
    print("📱 Adding Group 2 members...")
    broadcast_sms.add_member_to_group("+14257729189", 2, "Sam g")
    
    # GROUP 3 MEMBERS (MMS Group) - REPLACE WITH REAL NUMBERS
    print("📱 Adding Group 3 members...")
    broadcast_sms.add_member_to_group("+12065910943", 3, "sami drum")
    
    print("✅ All 3 groups setup complete!")
    print("💬 Now when anyone texts, it goes to ALL groups!")

@app.route('/webhook/sms', methods=['POST'])
def handle_sms():
    """Handle incoming SMS/MMS from Twilio - WITH MEDIA SUPPORT"""
    try:
        from_number = request.form.get('From', '').strip()
        message_body = request.form.get('Body', '').strip()
        
        # Handle media (pictures, audio, video)
        media_urls = []
        num_media = int(request.form.get('NumMedia', 0))
        
        for i in range(num_media):
            media_url = request.form.get(f'MediaUrl{i}')
            media_type = request.form.get(f'MediaContentType{i}')
            if media_url:
                media_urls.append({
                    'url': media_url,
                    'type': media_type
                })
        
        print(f"📱 Webhook: {from_number} -> {message_body}")
        if media_urls:
            print(f"📎 Media received: {len(media_urls)} files")
            for media in media_urls:
                print(f"   - {media['type']}: {media['url']}")
        
        if from_number:
            # Process text + media
            response_message = broadcast_sms.handle_sms_with_media(from_number, message_body, media_urls)
            
            # Only send response if there's a message (admin confirmations or help commands)
            if response_message:
                resp = MessagingResponse()
                resp.message(response_message)
                print(f"📤 Response: {response_message}")
                return str(resp)
            else:
                # No response needed (regular member message was broadcast)
                print(f"📤 Message processed, no response sent")
                return "OK", 200
        else:
            print("❌ Missing phone number")
            return "OK", 200
            
    except Exception as e:
        print(f"❌ Error: {e}")
        resp = MessagingResponse()
        resp.message("Sorry, there was an error processing your message.")
        return str(resp)

@app.route('/', methods=['GET'])
def home():
    return "🏛️ Multi-Group Broadcast SMS System with MMS Support is running!"

if __name__ == '__main__':
    print("🏛️ Starting Multi-Group Broadcast SMS System...")
    
    # Setup your congregation
    setup_your_congregation()
    
    print("\n🚀 Church SMS System Running with MMS Support!")
    print("📱 Text messages go to ALL groups!")
    print("📸 Photos/audio go to MMS group + text description to others!")
    
    # Use PORT environment variable for Render
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)