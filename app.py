from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import sqlite3
import re
from datetime import datetime
import os
import traceback

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
        print("🗄️ Initializing database...")
        try:
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
                print("✅ Created 3 congregation groups")
            
            conn.commit()
            conn.close()
            print("✅ Multi-Group Broadcast Database initialized!")
        except Exception as e:
            print(f"❌ Database initialization error: {e}")
            traceback.print_exc()
    
    def clean_phone_number(self, phone):
        """Clean and format phone number"""
        if not phone:
            return None
        digits = re.sub(r'\D', '', phone)
        if len(digits) == 10:
            return f"+1{digits}"
        elif len(digits) == 11 and digits.startswith('1'):
            return f"+{digits}"
        return phone
    
    def add_member_to_group(self, phone_number, group_id, name, is_admin=False):
        """Add a member to a specific group"""
        print(f"👤 Adding member: {name} ({phone_number}) to Group {group_id}")
        try:
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
            cursor.execute('''
                INSERT OR IGNORE INTO group_members (group_id, member_id) 
                VALUES (?, ?)
            ''', (group_id, member_id))
            conn.commit()
            conn.close()
            print(f"✅ Added {name} ({phone_number}) to Group {group_id}")
        except Exception as e:
            print(f"❌ Error adding member: {e}")
            traceback.print_exc()
    
    def get_all_members_across_groups(self, exclude_phone=None):
        """Get ALL members from ALL groups (no duplicates)"""
        print(f"📋 Getting all members (excluding {exclude_phone})")
        try:
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
            print(f"📋 Found {len(members)} members")
            return members
        except Exception as e:
            print(f"❌ Error getting members: {e}")
            traceback.print_exc()
            return []
    
    def get_member_groups(self, phone_number):
        """Get which groups a member belongs to"""
        try:
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
        except Exception as e:
            print(f"❌ Error getting member groups: {e}")
            return []
    
    def is_admin(self, phone_number):
        """Check if user is admin"""
        try:
            phone_number = self.clean_phone_number(phone_number)
            
            conn = sqlite3.connect('church_broadcast.db')
            cursor = conn.cursor()
            cursor.execute("SELECT is_admin FROM members WHERE phone_number = ?", (phone_number,))
            result = cursor.fetchone()
            conn.close()
            
            return bool(result[0]) if result else False
        except Exception as e:
            print(f"❌ Error checking admin status: {e}")
            return False
    
    def get_member_info(self, phone_number):
        """Get member information"""
        try:
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
                print(f"🆕 Auto-creating new member: {name}")
                self.add_member_to_group(phone_number, 1, name)  # Add to Group 1 by default
                return {"name": name, "is_admin": False}
        except Exception as e:
            print(f"❌ Error getting member info: {e}")
            return {"name": "Unknown", "is_admin": False}
    
    def supports_mms(self, phone_number):
        """Check if a member can receive MMS"""
        return True
    
    def broadcast_with_media(self, from_phone, message_text, media_urls, message_type='broadcast'):
        """Enhanced broadcast with comprehensive error handling and logging"""
        print(f"\n📡 ===== STARTING BROADCAST =====")
        print(f"👤 From: {from_phone}")
        print(f"📝 Message: '{message_text}'")
        print(f"📎 Media count: {len(media_urls) if media_urls else 0}")
        print(f"🏷️ Message type: {message_type}")
        
        try:
            sender = self.get_member_info(from_phone)
            print(f"👤 Sender info: {sender}")
            
            all_recipients = self.get_all_members_across_groups(exclude_phone=from_phone)
            print(f"📮 Recipients found: {len(all_recipients)}")
            
            if not all_recipients:
                print("❌ No recipients found - returning error message")
                return "No congregation members found to send to."
            
            # Validate and process media URLs
            valid_media_urls = []
            if media_urls:
                print(f"🔍 Validating {len(media_urls)} media files...")
                for i, media in enumerate(media_urls):
                    media_url = media.get('url', '')
                    media_type = media.get('type', '')
                    print(f"   Media {i+1}: {media_type} -> {media_url[:100]}...")
                    
                    if media_url and media_url.startswith('http'):
                        valid_media_urls.append(media_url)
                        print(f"   ✅ Valid media URL")
                    else:
                        print(f"   ❌ Invalid media URL")
                print(f"✅ {len(valid_media_urls)} valid media URLs found")
            
            # Store the broadcast message in database
            try:
                conn = sqlite3.connect('church_broadcast.db')
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO broadcast_messages (from_phone, from_name, message_text, message_type, has_media, media_count) 
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (from_phone, sender['name'], message_text, message_type, bool(valid_media_urls), len(valid_media_urls)))
                message_id = cursor.lastrowid
                
                # Store media URLs
                for media in media_urls:
                    cursor.execute('''
                        INSERT INTO message_media (message_id, media_url, media_type) 
                        VALUES (?, ?, ?)
                    ''', (message_id, media['url'], media['type']))
                
                conn.commit()
                conn.close()
                print(f"💾 Stored broadcast message with ID: {message_id}")
            except Exception as db_error:
                print(f"❌ Database storage error: {db_error}")
                message_id = None
            
            # Format message for recipients
            media_icon = ""
            if valid_media_urls:
                if any('image' in media.get('type', '') for media in media_urls):
                    media_icon = " 📸"
                elif any('audio' in media.get('type', '') for media in media_urls):
                    media_icon = " 🎵"
                elif any('video' in media.get('type', '') for media in media_urls):
                    media_icon = " 🎥"
                else:
                    media_icon = " 📎"
            
            formatted_message = f"💬 {sender['name']}:{media_icon}\n{message_text}"
            print(f"📝 Formatted message: {formatted_message}")
            
            # Send to ALL members with individual error handling
            sent_count = 0
            failed_count = 0
            mms_success = 0
            sms_fallback = 0
            
            print(f"📤 Starting delivery to {len(all_recipients)} recipients...")
            
            for i, recipient in enumerate(all_recipients):
                print(f"\n📱 Processing recipient {i+1}/{len(all_recipients)}: {recipient['name']} ({recipient['phone']})")
                recipient_groups = self.get_member_groups(recipient['phone'])
                
                try:
                    if valid_media_urls:
                        # Try MMS first
                        print(f"📸 Attempting MMS with {len(valid_media_urls)} media files...")
                        try:
                            if not self.client:
                                print("❌ No Twilio client available")
                                raise Exception("No Twilio client")
                            
                            message_obj = self.client.messages.create(
                                body=formatted_message,
                                from_=TWILIO_PHONE_NUMBER,
                                to=recipient['phone'],
                                media_url=valid_media_urls
                            )
                            mms_success += 1
                            print(f"✅ MMS sent successfully: {message_obj.sid}")
                            
                            # Log successful delivery
                            if message_id:
                                for group in recipient_groups:
                                    self.log_delivery(message_id, recipient['phone'], group['id'], 'sent', message_obj.sid, None, None, 'mms')
                            
                        except Exception as mms_error:
                            print(f"❌ MMS failed: {str(mms_error)}")
                            
                            # Try SMS fallback
                            print(f"📱 Attempting SMS fallback...")
                            try:
                                fallback_message = f"{formatted_message}\n\n📎 Media files were attached but couldn't be delivered to your device."
                                
                                sms_obj = self.client.messages.create(
                                    body=fallback_message,
                                    from_=TWILIO_PHONE_NUMBER,
                                    to=recipient['phone']
                                )
                                sms_fallback += 1
                                print(f"✅ SMS fallback sent: {sms_obj.sid}")
                                
                                # Log fallback delivery
                                if message_id:
                                    for group in recipient_groups:
                                        self.log_delivery(message_id, recipient['phone'], group['id'], 'sent_fallback', sms_obj.sid, getattr(mms_error, 'code', None), str(mms_error), 'sms')
                                
                            except Exception as sms_error:
                                print(f"❌ SMS fallback also failed: {str(sms_error)}")
                                failed_count += 1
                                
                                # Log complete failure
                                if message_id:
                                    for group in recipient_groups:
                                        self.log_delivery(message_id, recipient['phone'], group['id'], 'failed', None, getattr(sms_error, 'code', None), str(sms_error), 'sms')
                                continue
                    else:
                        # Send SMS only (no media)
                        print(f"📱 Sending SMS (no media)...")
                        if not self.client:
                            print("❌ No Twilio client available")
                            raise Exception("No Twilio client")
                        
                        message_obj = self.client.messages.create(
                            body=formatted_message,
                            from_=TWILIO_PHONE_NUMBER,
                            to=recipient['phone']
                        )
                        print(f"✅ SMS sent: {message_obj.sid}")
                        
                        # Log SMS delivery
                        if message_id:
                            for group in recipient_groups:
                                self.log_delivery(message_id, recipient['phone'], group['id'], 'sent', message_obj.sid, None, None, 'sms')
                    
                    sent_count += 1
                    
                except Exception as send_error:
                    failed_count += 1
                    print(f"❌ Failed to send to {recipient['phone']}: {send_error}")
                    print(f"🔍 Error type: {type(send_error).__name__}")
                    
                    # Log failure
                    if message_id:
                        for group in recipient_groups:
                            self.log_delivery(message_id, recipient['phone'], group['id'], 'failed', None, getattr(send_error, 'code', None), str(send_error), 'unknown')
            
            # Summary
            print(f"\n📊 ===== BROADCAST SUMMARY =====")
            print(f"✅ Total sent: {sent_count}")
            print(f"📸 MMS success: {mms_success}")
            print(f"📱 SMS fallback: {sms_fallback}")
            print(f"❌ Failed: {failed_count}")
            print(f"📋 Total recipients: {len(all_recipients)}")
            
            # Return admin confirmation
            if self.is_admin(from_phone):
                confirmation = f"✅ Broadcast complete: {sent_count}/{len(all_recipients)} delivered"
                if valid_media_urls:
                    confirmation += f"\n📸 MMS: {mms_success} success"
                    if sms_fallback > 0:
                        confirmation += f"\n📱 SMS fallback: {sms_fallback}"
                if failed_count > 0:
                    confirmation += f"\n❌ Failed: {failed_count}"
                return confirmation
            else:
                # For regular members, no confirmation message
                return None
                
        except Exception as broadcast_error:
            print(f"❌ CRITICAL BROADCAST ERROR: {broadcast_error}")
            print(f"🔍 Error type: {type(broadcast_error).__name__}")
            traceback.print_exc()
            return "Error processing broadcast - please try again"
        
        finally:
            print(f"🏁 ===== BROADCAST COMPLETED =====\n")
    
    def log_delivery(self, message_id, to_phone, to_group_id, status, twilio_sid=None, error_code=None, error_message=None, message_type='sms'):
        """Enhanced delivery logging with error details"""
        try:
            conn = sqlite3.connect('church_broadcast.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO delivery_log (message_id, to_phone, to_group_id, status, twilio_sid, error_code, error_message, message_type) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (message_id, to_phone, to_group_id, status, twilio_sid, error_code, error_message, message_type))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ Delivery logging error: {e}")
    
    def get_congregation_stats(self):
        """Get statistics about all groups"""
        try:
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
        except Exception as e:
            print(f"❌ Stats error: {e}")
            return "Error retrieving statistics"
    
    def handle_sms_with_media(self, from_phone, message_body, media_urls):
        """Main SMS handler with comprehensive logging"""
        print(f"\n📨 ===== PROCESSING MESSAGE =====")
        print(f"👤 From: {from_phone}")
        print(f"📝 Body: '{message_body}'")
        print(f"📎 Media count: {len(media_urls) if media_urls else 0}")
        
        try:
            from_phone = self.clean_phone_number(from_phone)
            message_body = message_body.strip() if message_body else ""
            
            if media_urls:
                for i, media in enumerate(media_urls):
                    print(f"📎 Media {i+1}: {media.get('type', 'unknown')} - {media.get('url', 'no URL')[:100]}...")
            
            # Ensure member exists (auto-add to Group 1 if new)
            member = self.get_member_info(from_phone)
            print(f"👤 Sender: {member['name']} (Admin: {member['is_admin']})")
            
            # Check for admin commands first
            if self.is_admin(from_phone) and message_body.upper().startswith(('STATS', 'HELP')):
                print(f"🔧 Processing admin command: {message_body}")
                if message_body.upper() == 'STATS':
                    return self.get_congregation_stats()
                elif message_body.upper() == 'HELP':
                    return ("📋 ADMIN COMMANDS:\n"
                           "• STATS - View congregation statistics\n"
                           "• HELP - Show this help")
            
            # DEFAULT: Broadcast message with media to ALL groups
            print(f"📡 Broadcasting to all groups...")
            return self.broadcast_with_media(from_phone, message_body, media_urls, 'broadcast')
            
        except Exception as processing_error:
            print(f"❌ MESSAGE PROCESSING ERROR: {processing_error}")
            print(f"🔍 Error type: {type(processing_error).__name__}")
            traceback.print_exc()
            return "Error processing your message - please try again"
        
        finally:
            print(f"🏁 ===== MESSAGE PROCESSING COMPLETED =====\n")

# Initialize the system
print("🏛️ Initializing Church SMS System...")
broadcast_sms = MultiGroupBroadcastSMS()

def setup_your_congregation():
    """Setup your 3 existing groups with real members"""
    print("🔧 Setting up your 3 congregation groups...")
    
    try:
        # Add yourself as admin
        broadcast_sms.add_member_to_group("+14257729189", 1, "Mike", is_admin=True)
        
        # GROUP 1 MEMBERS (SMS Group 1) 
        print("📱 Adding Group 1 members...")
        broadcast_sms.add_member_to_group("+12068001141", 1, "Mike")
        
        # GROUP 2 MEMBERS (SMS Group 2)  
        print("📱 Adding Group 2 members...")
        broadcast_sms.add_member_to_group("+14257729189", 2, "Sam g")
        
        # GROUP 3 MEMBERS (MMS Group)
        print("📱 Adding Group 3 members...")
        broadcast_sms.add_member_to_group("+12065910943", 3, "sami drum")
        broadcast_sms.add_member_to_group("+12064349652", 3, "yab")
        
        print("✅ All 3 groups setup complete!")
        print("💬 Now when anyone texts, it goes to ALL groups!")
    except Exception as e:
        print(f"❌ Setup error: {e}")
        traceback.print_exc()

# ===== FLASK ROUTES WITH COMPREHENSIVE DEBUGGING =====

@app.route('/webhook/sms', methods=['POST'])
def handle_sms():
    """ENHANCED: Handle incoming SMS/MMS with comprehensive error handling and debugging"""
    print(f"\n🌐 ===== WEBHOOK CALLED =====")
    print(f"📅 Timestamp: {datetime.now()}")
    print(f"🔍 Request method: {request.method}")
    print(f"📍 Request endpoint: {request.endpoint}")
    print(f"🌐 Request URL: {request.url}")
    print(f"📋 Request headers: {dict(request.headers)}")
    
    try:
        # Log all incoming form data for debugging
        print(f"📋 All form data:")
        for key, value in request.form.items():
            if key.startswith('MediaUrl'):
                print(f"   {key}: {value[:100]}...")  # Truncate long URLs
            else:
                print(f"   {key}: {value}")
        
        # Extract basic message info
        from_number = request.form.get('From', '').strip()
        message_body = request.form.get('Body', '').strip()
        
        print(f"📱 From: {from_number}")
        print(f"📝 Body: '{message_body}'")
        
        # Handle media with extensive logging
        media_urls = []
        num_media = int(request.form.get('NumMedia', 0))
        print(f"📎 NumMedia: {num_media}")
        
        for i in range(num_media):
            media_url = request.form.get(f'MediaUrl{i}')
            media_type = request.form.get(f'MediaContentType{i}')
            if media_url:
                media_urls.append({
                    'url': media_url,
                    'type': media_type or 'unknown'
                })
                print(f"📎 Media {i+1}: {media_type} -> {media_url[:100]}...")
        
        if not from_number:
            print("❌ ERROR: Missing From number in webhook")
            return "OK", 200
        
        print(f"🔄 Starting message processing...")
        
        # Process message with extensive error handling
        try:
            response_message = broadcast_sms.handle_sms_with_media(from_number, message_body, media_urls)
            print(f"✅ Message processing completed")
            print(f"📤 Response message: {response_message}")
            
            # Only send response if there's a message (admin confirmations)
            if response_message:
                resp = MessagingResponse()
                resp.message(response_message)
                response_xml = str(resp)
                print(f"📤 Sending TwiML response: {response_xml}")
                return response_xml
            else:
                print(f"📤 No response message - returning OK")
                return "OK", 200
                
        except Exception as processing_error:
            print(f"❌ ERROR in message processing: {processing_error}")
            print(f"🔍 Error type: {type(processing_error).__name__}")
            print(f"📋 Full traceback:")
            traceback.print_exc()
            
            # Return OK to prevent Twilio retries, but log the error
            return "OK", 200
            
    except Exception as webhook_error:
        print(f"❌ CRITICAL WEBHOOK ERROR: {webhook_error}")
        print(f"🔍 Error type: {type(webhook_error).__name__}")
        print(f"📋 Full traceback:")
        traceback.print_exc()
        
        # Always return OK to prevent Twilio retries
        return "OK", 200
    
    finally:
        print(f"🏁 ===== WEBHOOK COMPLETED =====\n")

@app.route('/test', methods=['GET', 'POST'])
def test_endpoint():
    """Test endpoint for debugging webhook functionality"""
    print(f"\n🧪 ===== TEST ENDPOINT CALLED =====")
    print(f"📅 Timestamp: {datetime.now()}")
    print(f"🔍 Method: {request.method}")
    
    try:
        if request.method == 'POST':
            print(f"📋 POST form data:")
            for key, value in request.form.items():
                print(f"   {key}: {value}")
            
            # Simulate webhook processing
            from_number = request.form.get('From', '+1234567890')
            message_body = request.form.get('Body', 'test message')
            
            print(f"🧪 Simulating message processing...")
            result = broadcast_sms.handle_sms_with_media(from_number, message_body, [])
            
            return jsonify({
                "status": "OK",
                "method": request.method,
                "timestamp": str(datetime.now()),
                "message": "Test processing completed",
                "result": result,
                "from": from_number,
                "body": message_body
            })
        else:
            return jsonify({
                "status": "OK",
                "method": request.method,
                "timestamp": str(datetime.now()),
                "message": "Test endpoint working - use POST to simulate webhook",
                "curl_test": "curl -X POST /test -d 'From=+1234567890&Body=test&NumMedia=0'"
            })
    except Exception as e:
        print(f"❌ Test endpoint error: {e}")
        traceback.print_exc()
        return jsonify({
            "status": "ERROR",
            "error": str(e),
            "timestamp": str(datetime.now())
        })
    finally:
        print(f"🏁 ===== TEST ENDPOINT COMPLETED =====\n")

@app.route('/', methods=['GET'])
def home():
    """Enhanced health check with comprehensive system status"""
    try:
        print(f"🏠 Home endpoint accessed at {datetime.now()}")
        
        # Test database connection
        conn = sqlite3.connect('church_broadcast.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM members")
        member_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM groups")
        group_count = cursor.fetchone()[0]
        conn.close()
        
        # Test Twilio client
        twilio_status = "✅ Connected" if broadcast_sms.client else "❌ No Client"
        
        # Check environment variables
        env_status = []
        env_status.append(f"Account SID: {'✅ Set' if TWILIO_ACCOUNT_SID else '❌ Missing'}")
        env_status.append(f"Auth Token: {'✅ Set' if TWILIO_AUTH_TOKEN else '❌ Missing'}")
        env_status.append(f"Phone Number: {'✅ Set' if TWILIO_PHONE_NUMBER else '❌ Missing'}")
        
        return f"""
🏛️ YesuWay Church SMS Broadcasting System

📊 SYSTEM STATUS:
✅ Application: Running
✅ Database: Connected ({member_count} members, {group_count} groups)
{twilio_status}

🔧 ENVIRONMENT:
{chr(10).join(env_status)}
Phone: {TWILIO_PHONE_NUMBER or 'NOT SET'}

📡 ENDPOINTS:
• Webhook: /webhook/sms (for Twilio)
• Test: /test (for debugging)
• Health: / (this page)

🕒 Last Check: {datetime.now()}

🧪 TEST WEBHOOK:
curl -X POST {request.host_url}test -d "From=+1234567890&Body=test&NumMedia=0"

Ready to receive messages! 📱📸🎵🎥
        """
        
    except Exception as e:
        print(f"❌ Health check error: {e}")
        traceback.print_exc()
        return f"❌ System Error: {e}", 500

@app.route('/webhook/status', methods=['POST'])
def handle_status_callback():
    """Handle delivery status callbacks from Twilio for debugging"""
    print(f"\n📊 ===== STATUS CALLBACK =====")
    print(f"📅 Timestamp: {datetime.now()}")
    
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
            
            # Log common error interpretations
            if error_code == '30007':
                print(f"   📱 Recipient device doesn't support MMS")
            elif error_code == '30008':
                print(f"   📊 Message blocked by carrier")
            elif error_code == '30034':
                print(f"   📋 A2P 10DLC registration issue")
            elif error_code in ['30035', '30036']:
                print(f"   📎 Media file issue (size/format)")
        else:
            print(f"   ✅ Message delivered successfully")
        
        return "OK", 200
        
    except Exception as e:
        print(f"❌ Status callback error: {e}")
        traceback.print_exc()
        return "OK", 200
    finally:
        print(f"🏁 ===== STATUS CALLBACK COMPLETED =====\n")

if __name__ == '__main__':
    print("🏛️ Starting Enhanced Multi-Group Broadcast SMS System...")
    print("🔧 Debug mode: ENABLED")
    print("📋 Comprehensive logging: ACTIVE")
    
    # Setup your congregation
    setup_your_congregation()
    
    print(f"\n🚀 Church SMS System Running!")
    print(f"📱 Webhook endpoint: /webhook/sms")
    print(f"🧪 Test endpoint: /test")
    print(f"📊 Health check: /")
    print(f"🔍 All events will be logged with detailed debugging")
    print(f"📸 MMS support with automatic SMS fallback enabled")
    
    # Use PORT environment variable for Render
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)