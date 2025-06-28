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
        if TWILIO_ACCOUNT_SID != "your_account_sid_here":
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
                message_type TEXT DEFAULT 'broadcast', -- broadcast, reaction, announcement
                thread_id INTEGER NULL,                 -- for conversation threading
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    
    def broadcast_to_all_groups(self, from_phone, message_text, message_type='broadcast'):
        """Send message to EVERYONE across ALL 3 groups"""
        sender = self.get_member_info(from_phone)
        all_recipients = self.get_all_members_across_groups(exclude_phone=from_phone)
        
        if not all_recipients:
            return "No congregation members found to send to."
        
        # Store the broadcast message
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO broadcast_messages (from_phone, from_name, message_text, message_type) 
            VALUES (?, ?, ?, ?)
        ''', (from_phone, sender['name'], message_text, message_type))
        message_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Format message for recipients
        if message_type == 'reaction':
            formatted_message = f"💭 {sender['name']} responded:\n{message_text}\n\n📱 Reply to join the conversation!"
        else:
            formatted_message = f"💬 {sender['name']}:\n{message_text}\n\n📱 Reply to join the conversation!"
        
        # Send to ALL members across ALL groups
        sent_count = 0
        failed_count = 0
        group_breakdown = {}
        
        for recipient in all_recipients:
            # Get recipient's groups for tracking
            recipient_groups = self.get_member_groups(recipient['phone'])
            
            if self.send_sms(recipient['phone'], formatted_message):
                sent_count += 1
                # Log delivery for each group they're in
                for group in recipient_groups:
                    self.log_delivery(message_id, recipient['phone'], group['id'], 'sent')
                    group_breakdown[group['name']] = group_breakdown.get(group['name'], 0) + 1
            else:
                failed_count += 1
                for group in recipient_groups:
                    self.log_delivery(message_id, recipient['phone'], group['id'], 'failed')
        
        # Create detailed confirmation
        confirmation = f"✅ Message broadcast to ALL GROUPS!\n"
        confirmation += f"📊 Total sent: {sent_count} members\n"
        if group_breakdown:
            confirmation += "📋 Group breakdown:\n"
            for group_name, count in group_breakdown.items():
                confirmation += f"  • {group_name}: {count} members\n"
        
        if failed_count > 0:
            confirmation += f"⚠️ Failed deliveries: {failed_count}"
        
        return confirmation
    
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
        
        conn.close()
        
        stats = f"📊 CONGREGATION STATISTICS\n\n"
        stats += f"👥 Total Active Members: {total_members}\n\n"
        stats += f"📋 Group Breakdown:\n"
        for group_name, count in group_stats:
            stats += f"  • {group_name}: {count} members\n"
        stats += f"\n📈 Messages this week: {recent_messages}"
        
        return stats
    
    def handle_sms(self, from_phone, message_body):
        """Main SMS handler for multi-group broadcasting"""
        from_phone = self.clean_phone_number(from_phone)
        message_body = message_body.strip()
        message_upper = message_body.upper()
        
        print(f"📨 Processing broadcast: {from_phone} -> {message_body}")
        
        # Ensure member exists (auto-add to Group 1 if new)
        member = self.get_member_info(from_phone)
        
        # HELP command
        if message_upper in ['HELP', 'H', '?']:
            help_text = "🏛️ MULTI-GROUP BROADCAST SYSTEM\n\n"
            help_text += "📢 HOW IT WORKS:\n"
            help_text += "• Text anything → Goes to ALL 3 congregation groups!\n"
            help_text += "• All reactions → Go to ALL groups\n"
            help_text += "• Everyone sees everything across all groups\n\n"
            help_text += "📱 COMMANDS:\n"
            help_text += "• HELP - Show this message\n"
            help_text += "• STATS - Show congregation statistics\n"
            help_text += "• GROUPS - Show which groups you're in\n\n"
            
            if self.is_admin(from_phone):
                help_text += "👑 ADMIN COMMANDS:\n"
                help_text += "• ADD [phone] [name] TO [group_id] - Add member\n"
                help_text += "• RECENT - View recent broadcasts\n"
            
            help_text += "💬 Just type your message to broadcast to everyone!"
            return help_text
        
        # STATS command
        elif message_upper == 'STATS':
            return self.get_congregation_stats()
        
        # GROUPS command
        elif message_upper == 'GROUPS':
            groups = self.get_member_groups(from_phone)
            if not groups:
                return "You're not in any groups yet. Contact admin to be added."
            
            response = f"📋 Your Groups:\n"
            for group in groups:
                response += f"  • {group['name']}\n"
            response += f"\n💬 Your messages go to ALL congregation groups!"
            return response
        
        # ADMIN COMMANDS
        elif self.is_admin(from_phone):
            if message_upper.startswith('ADD ') and ' TO ' in message_upper:
                try:
                    # Parse: ADD +1234567890 John Smith TO 1
                    parts = message_body[4:].split(' TO ')
                    if len(parts) == 2:
                        contact_info = parts[0].strip().split(' ', 1)
                        phone = contact_info[0]
                        name = contact_info[1] if len(contact_info) > 1 else f"Member {phone[-4:]}"
                        group_id = int(parts[1].strip())
                        
                        self.add_member_to_group(phone, group_id, name)
                        return f"✅ Added {name} ({phone}) to Group {group_id}"
                    else:
                        return "Format: ADD [phone] [name] TO [group_id]"
                except Exception as e:
                    return f"❌ Error: {e}"
            
            elif message_upper == 'RECENT':
                conn = sqlite3.connect('church_broadcast.db')
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT from_name, message_text, message_type, sent_at 
                    FROM broadcast_messages 
                    ORDER BY sent_at DESC 
                    LIMIT 5
                ''')
                messages = cursor.fetchall()
                conn.close()
                
                if not messages:
                    return "No recent broadcasts."
                
                result = "📋 Recent Broadcasts:\n\n"
                for msg in messages:
                    result += f"👤 {msg[0]} ({msg[2]})\n💬 {msg[1][:50]}...\n🕐 {msg[3][:16]}\n\n"
                return result
        
        # DEFAULT: Broadcast message to ALL groups
        else:
            return self.broadcast_to_all_groups(from_phone, message_body, 'broadcast')

# Initialize the system
broadcast_sms = MultiGroupBroadcastSMS()

def setup_your_congregation():
    """Setup your 3 existing groups with real members"""
    print("🔧 Setting up your 3 congregation groups...")
    
    # Add yourself as admin
    broadcast_sms.add_member_to_group("+14257729189", 1, "Mike", is_admin=True)
    
    # GROUP 1 MEMBERS (SMS Group 1) - REPLACE WITH REAL NUMBERS
    print("📱 Adding Group 1 members...")
    # broadcast_sms.add_member_to_group("+15408357329", 1, "barok")
    broadcast_sms.add_member_to_group("+12068001141", 1, "Mike")
    # broadcast_sms.add_member_to_group("+1234567892", 1, "David Wilson")
    
    # GROUP 2 MEMBERS (SMS Group 2) - REPLACE WITH REAL NUMBERS  
    print("📱 Adding Group 2 members...")
    broadcast_sms.add_member_to_group("+14257729189", 2, "Sam g")
    # broadcast_sms.add_member_to_group("+1234567894", 2, "Michael Brown")
    # broadcast_sms.add_member_to_group("+1234567895", 2, "Lisa Garcia")
    
    # GROUP 3 MEMBERS (MMS Group) - REPLACE WITH REAL NUMBERS
    print("📱 Adding Group 3 members...")
    broadcast_sms.add_member_to_group("+12065910943", 3, "sami drum")
    # broadcast_sms.add_member_to_group("+1234567897", 3, "Jennifer Wilson")
    # broadcast_sms.add_member_to_group("+1234567898", 3, "Christopher Moore")
    
    print("✅ All 3 groups setup complete!")
    print("💬 Now when anyone texts, it goes to ALL groups!")

@app.route('/webhook/sms', methods=['POST'])
def handle_sms():
    """Handle incoming SMS from Twilio"""
    try:
        from_number = request.form.get('From', '').strip()
        message_body = request.form.get('Body', '').strip()
        
        print(f"📱 Webhook: {from_number} -> {message_body}")
        
        if from_number and message_body:
            response_message = broadcast_sms.handle_sms(from_number, message_body)
            
            resp = MessagingResponse()
            resp.message(response_message)
            
            print(f"📤 Response: {response_message}")
            return str(resp)
        else:
            print("❌ Missing fields")
            return "OK", 200
            
    except Exception as e:
        print(f"❌ Error: {e}")
        resp = MessagingResponse()
        return str(resp)

@app.route('/', methods=['GET'])
def home():
    return "🏛️ Multi-Group Broadcast SMS System is running!"

if __name__ == '__main__':
    print("🏛️ Starting Multi-Group Broadcast SMS System...")
    
    # Setup your congregation
    setup_your_congregation()
    
    print("\n🚀 Church SMS System Running on Heroku!")
    
    # Use PORT environment variable for Heroku
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False) 