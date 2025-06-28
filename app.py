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
        
        # Enhanced delivery tracking with error details
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS delivery_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                to_phone TEXT NOT NULL,
                to_group_id INTEGER NOT NULL,
                delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'sent',
                twilio_sid TEXT NULL,
                error_code TEXT NULL,
                error_message TEXT NULL,
                message_type TEXT DEFAULT 'sms',
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
        return True
    
    def validate_and_process_media_urls(self, media_urls):
        """Validate and process media URLs from Twilio webhook"""
        if not media_urls:
            return []
        
        processed_media = []
        print(f"🔍 Processing {len(media_urls)} media files...")
        
        for i, media in enumerate(media_urls):
            media_url = media.get('url', '')
            media_type = media.get('type', '')
            
            print(f"   Media {i+1}: {media_type} -> {media_url}")
            
            # Validate URL format
            if media_url and media_url.startswith('http'):
                # Check if it's a supported media type
                supported_types = [
                    'image/jpeg', 'image/jpg', 'image/png', 'image/gif',
                    'video/mp4', 'video/mov', 'video/quicktime', 'video/3gpp',
                    'audio/mp3', 'audio/mpeg', 'audio/wav', 'audio/amr'
                ]
                
                if any(supported in media_type.lower() for supported in ['image/', 'video/', 'audio/']):
                    processed_media.append({
                        'url': media_url,
                        'type': media_type
                    })
                    print(f"   ✅ Valid media: {media_type}")
                else:
                    print(f"   ⚠️ Unsupported media type: {media_type}")
            else:
                print(f"   ❌ Invalid URL: {media_url}")
        
        print(f"✅ Processed {len(processed_media)} valid media files")
        return processed_media
    
    def broadcast_with_media(self, from_phone, message_text, media_urls, message_type='broadcast'):
        """ENHANCED: Send message WITH media to EVERYONE across ALL 3 groups"""
        print(f"\n📡 Starting broadcast from {from_phone}")
        print(f"📝 Message: {message_text}")
        print(f"📎 Media files: {len(media_urls) if media_urls else 0}")
        
        sender = self.get_member_info(from_phone)
        all_recipients = self.get_all_members_across_groups(exclude_phone=from_phone)
        
        if not all_recipients:
            return "No congregation members found to send to."
        
        # Process and validate media URLs
        valid_media = self.validate_and_process_media_urls(media_urls)
        
        # Store the broadcast message
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO broadcast_messages (from_phone, from_name, message_text, message_type, has_media, media_count) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (from_phone, sender['name'], message_text, message_type, bool(valid_media), len(valid_media)))
        message_id = cursor.lastrowid
        
        # Store media URLs
        for media in valid_media:
            cursor.execute('''
                INSERT INTO message_media (message_id, media_url, media_type) 
                VALUES (?, ?, ?)
            ''', (message_id, media['url'], media['type']))
        
        conn.commit()
        conn.close()
        
        # Format message for recipients
        media_text = ""
        if valid_media:
            media_count = len(valid_media)
            media_types = [media['type'].split('/')[0] for media in valid_media]
            if 'image' in media_types:
                media_text = f" 📸"
            elif 'audio' in media_types:
                media_text = f" 🎵"
            elif 'video' in media_types:
                media_text = f" 🎥"
            else:
                media_text = f" 📎"
        
        if message_type == 'reaction':
            formatted_message = f"💭 {sender['name']} responded:\n{message_text}"
        else:
            formatted_message = f"💬 {sender['name']}:{media_text}\n{message_text}"
        
        # Send to ALL members across ALL groups with improved error handling
        sent_count = 0
        failed_count = 0
        mms_success = 0
        mms_failed = 0
        sms_fallback = 0
        
        print(f"📤 Broadcasting to {len(all_recipients)} recipients...")
        
        for i, recipient in enumerate(all_recipients):
            recipient_groups = self.get_member_groups(recipient['phone'])
            print(f"📱 Sending to {recipient['name']} ({recipient['phone']}) - {i+1}/{len(all_recipients)}")
            
            try:
                if valid_media:
                    # Try MMS with media first
                    print(f"   📸 Attempting MMS with {len(valid_media)} media files...")
                    try:
                        # Extract just the URLs for Twilio API
                        media_urls_only = [media['url'] for media in valid_media]
                        
                        message_obj = self.client.messages.create(
                            body=formatted_message,
                            from_=TWILIO_PHONE_NUMBER,
                            to=recipient['phone'],
                            media_url=media_urls_only
                        )
                        mms_success += 1
                        print(f"   ✅ MMS sent successfully: {message_obj.sid}")
                        
                        # Log successful MMS delivery
                        for group in recipient_groups:
                            self.log_delivery(message_id, recipient['phone'], group['id'], 'sent', message_obj.sid, None, None, 'mms')
                            
                    except Exception as mms_error:
                        print(f"   ❌ MMS failed: {str(mms_error)}")
                        mms_failed += 1
                        
                        # Extract error details
                        error_code = getattr(mms_error, 'code', None)
                        error_msg = str(mms_error)
                        
                        # Log MMS failure
                        for group in recipient_groups:
                            self.log_delivery(message_id, recipient['phone'], group['id'], 'failed', None, error_code, error_msg, 'mms')
                        
                        # Fallback to SMS with media description
                        print(f"   📱 Trying SMS fallback...")
                        try:
                            fallback_message = f"{formatted_message}\n\n📎 Media files were attached but couldn't be delivered to your device."
                            
                            sms_obj = self.client.messages.create(
                                body=fallback_message,
                                from_=TWILIO_PHONE_NUMBER,
                                to=recipient['phone']
                            )
                            sms_fallback += 1
                            print(f"   ✅ SMS fallback sent: {sms_obj.sid}")
                            
                            # Log SMS fallback success
                            for group in recipient_groups:
                                self.log_delivery(message_id, recipient['phone'], group['id'], 'sent_fallback', sms_obj.sid, None, None, 'sms')
                            
                        except Exception as sms_error:
                            print(f"   ❌ SMS fallback also failed: {str(sms_error)}")
                            failed_count += 1
                            
                            # Log complete failure
                            for group in recipient_groups:
                                self.log_delivery(message_id, recipient['phone'], group['id'], 'failed', None, getattr(sms_error, 'code', None), str(sms_error), 'sms')
                            continue
                else:
                    # Send SMS only (no media)
                    print(f"   📱 Sending SMS...")
                    message_obj = self.client.messages.create(
                        body=formatted_message,
                        from_=TWILIO_PHONE_NUMBER,
                        to=recipient['phone']
                    )
                    print(f"   ✅ SMS sent: {message_obj.sid}")
                    
                    # Log SMS delivery
                    for group in recipient_groups:
                        self.log_delivery(message_id, recipient['phone'], group['id'], 'sent', message_obj.sid, None, None, 'sms')

                sent_count += 1
                
            except Exception as e:
                failed_count += 1
                print(f"   ❌ Complete failure for {recipient['phone']}: {e}")
                for group in recipient_groups:
                    self.log_delivery(message_id, recipient['phone'], group['id'], 'failed', None, getattr(e, 'code', None), str(e), 'unknown')
        
        # Enhanced admin confirmation with detailed stats
        print(f"\n📊 Broadcast Summary:")
        print(f"   ✅ Successful: {sent_count}")
        print(f"   📸 MMS Success: {mms_success}")
        print(f"   📱 SMS Fallback: {sms_fallback}")
        print(f"   ❌ MMS Failed: {mms_failed}")
        print(f"   ❌ Total Failed: {failed_count}")
        
        if self.is_admin(from_phone):
            confirmation = f"✅ Broadcast complete: {sent_count}/{len(all_recipients)} delivered"
            if valid_media:
                confirmation += f"\n📸 MMS: {mms_success} success"
                if mms_failed > 0:
                    confirmation += f", {mms_failed} failed"
                if sms_fallback > 0:
                    confirmation += f"\n📱 SMS fallback: {sms_fallback}"
            if failed_count > 0:
                confirmation += f"\n❌ Failed: {failed_count}"
            return confirmation
        else:
            # For regular members, no confirmation message
            return None
    
    def log_delivery(self, message_id, to_phone, to_group_id, status, twilio_sid=None, error_code=None, error_message=None, message_type='sms'):
        """Enhanced delivery logging with error details"""
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO delivery_log (message_id, to_phone, to_group_id, status, twilio_sid, error_code, error_message, message_type) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (message_id, to_phone, to_group_id, status, twilio_sid, error_code, error_message, message_type))
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
        
        # MMS success rate
        cursor.execute('''
            SELECT 
                COUNT(CASE WHEN message_type = 'mms' AND status = 'sent' THEN 1 END) as mms_success,
                COUNT(CASE WHEN message_type = 'mms' THEN 1 END) as mms_total
            FROM delivery_log 
            WHERE delivered_at > datetime('now', '-7 days')
        ''')
        mms_stats = cursor.fetchone()
        
        conn.close()
        
        stats = f"📊 CONGREGATION STATISTICS\n\n"
        stats += f"👥 Total Active Members: {total_members}\n\n"
        stats += f"📋 Group Breakdown:\n"
        for group_name, count in group_stats:
            stats += f"  • {group_name}: {count} members\n"
        stats += f"\n📈 Messages this week: {recent_messages}"
        stats += f"\n📎 Media messages: {recent_media}"
        
        if mms_stats and mms_stats[1] > 0:
            mms_success_rate = (mms_stats[0] / mms_stats[1]) * 100
            stats += f"\n📸 MMS success rate: {mms_success_rate:.1f}%"
        
        return stats
    
    def handle_sms_with_media(self, from_phone, message_body, media_urls):
        """ENHANCED: Main SMS handler for multi-group broadcasting with media support"""
        from_phone = self.clean_phone_number(from_phone)
        message_body = message_body.strip() if message_body else ""
        
        print(f"\n📨 Processing message from {from_phone}")
        print(f"📝 Body: '{message_body}'")
        print(f"📎 Media count: {len(media_urls) if media_urls else 0}")
        
        if media_urls:
            for i, media in enumerate(media_urls):
                print(f"   Media {i+1}: {media.get('type', 'unknown')} - {media.get('url', 'no URL')[:50]}...")
        
        # Ensure member exists (auto-add to Group 1 if new)
        member = self.get_member_info(from_phone)
        print(f"👤 Sender: {member['name']} (Admin: {member['is_admin']})")
        
        # Check for admin commands first
        if self.is_admin(from_phone) and message_body.upper().startswith(('ADD ', 'STATS', 'RECENT', 'HELP')):
            return self.handle_admin_commands(from_phone, message_body)
        
        # DEFAULT: Broadcast message with media to ALL groups
        return self.broadcast_with_media(from_phone, message_body, media_urls, 'broadcast')
    
    def handle_admin_commands(self, from_phone, message_body):
        """Handle admin-only commands"""
        command = message_body.upper().strip()
        
        if command == 'STATS':
            return self.get_congregation_stats()
        elif command == 'HELP':
            return ("📋 ADMIN COMMANDS:\n"
                   "• STATS - View congregation statistics\n"
                   "• ADD +1234567890 Name TO 1 - Add member to group\n"
                   "• RECENT - View recent broadcasts\n"
                   "• HELP - Show this help")
        elif command == 'RECENT':
            return self.get_recent_broadcasts()
        elif command.startswith('ADD '):
            return self.handle_add_member_command(message_body)
        else:
            return None
    
    def get_recent_broadcasts(self):
        """Get recent broadcast messages for admin"""
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT from_name, message_text, has_media, sent_at 
            FROM broadcast_messages 
            ORDER BY sent_at DESC 
            LIMIT 5
        ''')
        recent = cursor.fetchall()
        conn.close()
        
        if not recent:
            return "No recent broadcasts found."
        
        result = "📋 RECENT BROADCASTS:\n\n"
        for i, (name, text, has_media, sent_at) in enumerate(recent, 1):
            media_icon = " 📎" if has_media else ""
            # Truncate long messages
            display_text = text[:50] + "..." if len(text) > 50 else text
            result += f"{i}. {name}{media_icon}: {display_text}\n"
        
        return result
    
    def handle_add_member_command(self, message_body):
        """Handle ADD member command"""
        # Parse: ADD +1234567890 John Smith TO 1
        try:
            parts = message_body.split()
            if len(parts) < 5 or parts[0].upper() != 'ADD' or parts[-2].upper() != 'TO':
                return "❌ Format: ADD +1234567890 First Last TO 1"
            
            phone = parts[1]
            group_id = int(parts[-1])
            name = ' '.join(parts[2:-2])
            
            if group_id not in [1, 2, 3]:
                return "❌ Group must be 1, 2, or 3"
            
            self.add_member_to_group(phone, group_id, name)
            return f"✅ Added {name} to Group {group_id}"
            
        except Exception as e:
            return f"❌ Error adding member: {str(e)}"

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
    broadcast_sms.add_member_to_group("+12064349652", 3, "yab")
    
    print("✅ All 3 groups setup complete!")
    print("💬 Now when anyone texts, it goes to ALL groups!")

@app.route('/webhook/sms', methods=['POST'])
def handle_sms():
    """ENHANCED: Handle incoming SMS/MMS from Twilio - WITH PROPER MEDIA SUPPORT"""
    try:
        from_number = request.form.get('From', '').strip()
        message_body = request.form.get('Body', '').strip()
        
        # Enhanced media handling
        media_urls = []
        num_media = int(request.form.get('NumMedia', 0))
        
        print(f"\n🌐 Webhook received from {from_number}")
        print(f"📝 Body: '{message_body}'")
        print(f"📎 NumMedia: {num_media}")
        
        for i in range(num_media):
            media_url = request.form.get(f'MediaUrl{i}')
            media_type = request.form.get(f'MediaContentType{i}')
            
            if media_url:
                media_urls.append({
                    'url': media_url,
                    'type': media_type or 'unknown'
                })
                print(f"📎 Media {i+1}: {media_type} -> {media_url}")
        
        if from_number:
            # Process text + media with enhanced error handling
            try:
                response_message = broadcast_sms.handle_sms_with_media(from_number, message_body, media_urls)
                
                # Only send response if there's a message (admin confirmations or help commands)
                if response_message:
                    resp = MessagingResponse()
                    resp.message(response_message)
                    print(f"📤 Sending response: {response_message[:100]}...")
                    return str(resp)
                else:
                    # No response needed (regular member message was broadcast)
                    print(f"📤 Message broadcast complete, no response sent")
                    return "OK", 200
                    
            except Exception as processing_error:
                print(f"❌ Error processing message: {processing_error}")
                resp = MessagingResponse()
                resp.message("Sorry, there was an error processing your message. Please try again.")
                return str(resp)
        else:
            print("❌ Missing sender phone number")
            return "OK", 200
            
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        # Return OK to prevent Twilio retries on our errors
        return "OK", 200

@app.route('/webhook/status', methods=['POST'])
def handle_status_callback():
    """Handle delivery status callbacks from Twilio for debugging"""
    try:
        message_sid = request.form.get('MessageSid')
        message_status = request.form.get('MessageStatus')
        to_number = request.form.get('To')
        error_code = request.form.get('ErrorCode')
        error_message = request.form.get('ErrorMessage')
        
        print(f"📊 Status Update for {message_sid}:")
        print(f"   To: {to_number}")
        print(f"   Status: {message_status}")
        
        if error_code:
            print(f"   ❌ Error {error_code}: {error_message}")
        
        return "OK", 200
        
    except Exception as e:
        print(f"❌ Status callback error: {e}")
        return "OK", 200

@app.route('/', methods=['GET'])
def home():
    return "🏛️ Multi-Group Broadcast SMS System with ENHANCED MMS Support is running!"

if __name__ == '__main__':
    print("🏛️ Starting Enhanced Multi-Group Broadcast SMS System...")
    
    # Setup your congregation
    setup_your_congregation()
    
    print("\n🚀 Church SMS System Running with ENHANCED MMS Support!")
    print("📱 All messages broadcast to entire congregation!")
    print("📸 MMS with automatic SMS fallback for failed deliveries!")
    print("📊 Detailed logging and error tracking enabled!")
    
    # Use PORT environment variable for Render
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)