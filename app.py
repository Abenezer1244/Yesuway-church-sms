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
        """Check if a member can receive MMS - now everyone can!"""
        # Since your Twilio number and campaign support MMS,
        # and most modern phones support MMS, let's enable it for everyone
        return True
    
    def broadcast_with_media(self, from_phone, message_text, media_urls, message_type='broadcast'):
        """SPEED OPTIMIZED: Send message WITH media to EVERYONE across ALL 3 groups"""
        print(f"\n📡 ===== STARTING BROADCAST (SPEED OPTIMIZED) =====")
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
            
            # SPEED CRITICAL: Quick media validation (minimal processing)
            valid_media_urls = []
            if media_urls:
                print(f"🔍 Quick validating {len(media_urls)} media files...")
                for i, media in enumerate(media_urls):
                    media_url = media.get('url', '')
                    media_type = media.get('type', '')
                    print(f"   Media {i+1}: {media_type} -> {media_url[:100]}...")
                    
                    if media_url and media_url.startswith('http'):
                        # Additional validation for supported types
                        supported_types = [
                            'image/jpeg', 'image/jpg', 'image/png', 'image/gif',
                            'video/mp4', 'video/mov', 'video/quicktime', 'video/3gpp',
                            'audio/mp3', 'audio/mpeg', 'audio/wav', 'audio/amr'
                        ]
                        
                        if any(supported in media_type.lower() for supported in ['image/', 'video/', 'audio/']):
                            valid_media_urls.append(media_url)
                            print(f"   ✅ Valid media URL")
                        else:
                            print(f"   ⚠️ Unsupported media type: {media_type}")
                    else:
                        print(f"   ❌ Invalid URL: {media_url}")
                print(f"✅ {len(valid_media_urls)} valid media URLs found")
            
            # Store the broadcast message in database (async, don't wait for completion)
            message_id = None
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
            
            # Format message for recipients (simple and fast)
            media_text = ""
            if valid_media_urls:
                media_count = len(valid_media_urls)
                media_types = [media['type'].split('/')[0] for media in media_urls]
                if 'image' in media_types:
                    media_text = f" 📸"
                elif 'audio' in media_types:
                    media_text = f" 🎵"
                elif 'video' in media_types:
                    media_text = f" 🎥"
                else:
                    media_text = f" 📎"
            
            if message_type == 'reaction':
                formatted_message = f"💭 {sender['name']} responded:\n{message_text}{media_text}"
            else:
                formatted_message = f"💬 {sender['name']}:{media_text}\n{message_text}"
            
            print(f"📝 Formatted message: {formatted_message}")
            
            # SPEED CRITICAL: Fast delivery with minimal logging during send
            sent_count = 0
            failed_count = 0
            mms_sent = 0
            sms_sent = 0
            mms_failed = 0
            sms_fallback = 0
            group_breakdown = {}
            
            print(f"📤 FAST delivery to {len(all_recipients)} recipients...")
            
            for i, recipient in enumerate(all_recipients):
                print(f"📱 {i+1}/{len(all_recipients)}: {recipient['name']} ({recipient['phone']})")
                
                # Get recipient's groups for tracking
                recipient_groups = self.get_member_groups(recipient['phone'])
                
                try:
                    if valid_media_urls:
                        # Try MMS first - SPEED OPTIMIZED
                        try:
                            if not self.client:
                                raise Exception("No Twilio client available")
                            
                            message_obj = self.client.messages.create(
                                body=formatted_message,
                                from_=TWILIO_PHONE_NUMBER,
                                to=recipient['phone'],
                                media_url=valid_media_urls  # List of clean URLs
                            )
                            mms_sent += 1
                            print(f"✅ MMS: {message_obj.sid}")
                            
                            # Quick delivery logging (if message_id exists)
                            if message_id:
                                for group in recipient_groups:
                                    self.log_delivery_fast(message_id, recipient['phone'], group['id'], 'sent', message_obj.sid, 'mms')
                                    group_breakdown[group['name']] = group_breakdown.get(group['name'], 0) + 1
                            
                        except Exception as mms_error:
                            mms_failed += 1
                            print(f"❌ MMS failed: {str(mms_error)[:50]}...")
                            
                            # SPEED CRITICAL: Quick SMS fallback
                            try:
                                fallback_message = f"{formatted_message}\n\n📎 Media files were attached but couldn't be delivered to your device."
                                
                                sms_obj = self.client.messages.create(
                                    body=fallback_message,
                                    from_=TWILIO_PHONE_NUMBER,
                                    to=recipient['phone']
                                )
                                sms_fallback += 1
                                print(f"✅ SMS fallback: {sms_obj.sid}")
                                
                                # Quick logging
                                if message_id:
                                    for group in recipient_groups:
                                        self.log_delivery_fast(message_id, recipient['phone'], group['id'], 'sent_fallback', sms_obj.sid, 'sms')
                                        group_breakdown[group['name']] = group_breakdown.get(group['name'], 0) + 1
                                
                            except Exception as sms_error:
                                failed_count += 1
                                print(f"❌ SMS fallback failed: {str(sms_error)[:50]}...")
                                
                                # Log complete failure
                                if message_id:
                                    for group in recipient_groups:
                                        self.log_delivery_fast(message_id, recipient['phone'], group['id'], 'failed', None, 'failed')
                                continue
                    else:
                        # Send SMS only (no media) - SPEED OPTIMIZED
                        if not self.client:
                            raise Exception("No Twilio client available")
                        
                        message_obj = self.client.messages.create(
                            body=formatted_message,
                            from_=TWILIO_PHONE_NUMBER,
                            to=recipient['phone']
                        )
                        sms_sent += 1
                        print(f"✅ SMS: {message_obj.sid}")
                        
                        # Quick logging
                        if message_id:
                            for group in recipient_groups:
                                self.log_delivery_fast(message_id, recipient['phone'], group['id'], 'sent', message_obj.sid, 'sms')
                                group_breakdown[group['name']] = group_breakdown.get(group['name'], 0) + 1
                    
                    sent_count += 1
                    
                except Exception as send_error:
                    failed_count += 1
                    print(f"❌ Failed: {str(send_error)[:50]}...")
                    
                    # Quick failure logging
                    if message_id:
                        for group in recipient_groups:
                            self.log_delivery_fast(message_id, recipient['phone'], group['id'], 'failed', None, 'failed')
            
            # Enhanced summary
            print(f"\n📊 ===== BROADCAST SUMMARY =====")
            print(f"✅ Total sent: {sent_count}")
            print(f"📸 MMS success: {mms_sent}")
            print(f"📱 SMS fallback: {sms_fallback}")
            print(f"📱 SMS only: {sms_sent}")
            print(f"❌ MMS failed: {mms_failed}")
            print(f"❌ Total failed: {failed_count}")
            print(f"📋 Total recipients: {len(all_recipients)}")
            
            # Create enhanced admin confirmation (only for admin)
            if self.is_admin(from_phone):
                confirmation = f"✅ Broadcast complete: {sent_count}/{len(all_recipients)} delivered"
                if valid_media_urls:
                    confirmation += f"\n📸 MMS: {mms_sent} success"
                    if mms_failed > 0:
                        confirmation += f", {mms_failed} failed"
                    if sms_fallback > 0:
                        confirmation += f"\n📱 SMS fallback: {sms_fallback}"
                if sms_sent > 0:
                    confirmation += f"\n📱 SMS only: {sms_sent}"
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
    
    def log_delivery_fast(self, message_id, to_phone, to_group_id, status, twilio_sid=None, message_type='sms'):
        """Fast delivery logging without detailed error tracking (for speed)"""
        try:
            conn = sqlite3.connect('church_broadcast.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO delivery_log (message_id, to_phone, to_group_id, status, twilio_sid, message_type) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (message_id, to_phone, to_group_id, status, twilio_sid, message_type))
            conn.commit()
            conn.close()
        except Exception as e:
            # Don't log delivery logging errors to avoid slowing down
            pass
    
    def log_delivery(self, message_id, to_phone, to_group_id, status, twilio_sid=None, error_code=None, error_message=None, message_type='sms'):
        """Enhanced delivery logging with error details (for non-speed-critical operations)"""
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
            
            # MMS success rate
            cursor.execute('''
                SELECT 
                    COUNT(CASE WHEN message_type = 'mms' AND status = 'sent' THEN 1 END) as mms_success,
                    COUNT(CASE WHEN message_type = 'mms' THEN 1 END) as mms_total,
                    COUNT(CASE WHEN status = 'sent_fallback' THEN 1 END) as sms_fallback
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
                if mms_stats[2] > 0:
                    stats += f"\n📱 SMS fallbacks: {mms_stats[2]}"
            
            return stats
        except Exception as e:
            print(f"❌ Stats error: {e}")
            return "Error retrieving statistics"
    
    def get_recent_broadcasts(self):
        """Get recent broadcast messages for admin"""
        try:
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
                # Format timestamp
                try:
                    dt = datetime.fromisoformat(sent_at.replace('Z', '+00:00'))
                    time_str = dt.strftime('%m/%d %H:%M')
                except:
                    time_str = sent_at[-8:-3] if len(sent_at) > 8 else sent_at
                result += f"{i}. {name}{media_icon} ({time_str}): {display_text}\n"
            
            return result
        except Exception as e:
            print(f"❌ Recent broadcasts error: {e}")
            return "Error retrieving recent broadcasts"
    
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
                   "• GROUPS - Show group structure\n"
                   "• HELP - Show this help")
        elif command == 'RECENT':
            return self.get_recent_broadcasts()
        elif command == 'GROUPS':
            return self.get_group_structure()
        elif command.startswith('ADD '):
            return self.handle_add_member_command(message_body)
        else:
            return None
    
    def get_group_structure(self):
        """Get group structure for admin"""
        try:
            conn = sqlite3.connect('church_broadcast.db')
            cursor = conn.cursor()
            cursor.execute('''
                SELECT g.id, g.name, g.description, COUNT(DISTINCT m.id) as member_count
                FROM groups g
                LEFT JOIN group_members gm ON g.id = gm.group_id
                LEFT JOIN members m ON gm.member_id = m.id AND m.active = 1
                GROUP BY g.id, g.name, g.description
                ORDER BY g.id
            ''')
            groups = cursor.fetchall()
            
            # Get sample members for each group
            result = "📋 GROUP STRUCTURE:\n\n"
            for group_id, name, desc, count in groups:
                result += f"🏷️ {name} (ID: {group_id})\n"
                result += f"   📝 {desc}\n"
                result += f"   👥 {count} members\n"
                
                # Get sample members
                cursor.execute('''
                    SELECT m.name, m.phone_number, m.is_admin
                    FROM members m
                    JOIN group_members gm ON m.id = gm.member_id
                    WHERE gm.group_id = ? AND m.active = 1
                    LIMIT 3
                ''', (group_id,))
                members = cursor.fetchall()
                
                if members:
                    result += "   📞 Members: "
                    member_names = []
                    for name, phone, is_admin in members:
                        admin_marker = " (Admin)" if is_admin else ""
                        member_names.append(f"{name}{admin_marker}")
                    result += ", ".join(member_names)
                    if count > 3:
                        result += f" +{count-3} more"
                result += "\n\n"
            
            conn.close()
            return result
        except Exception as e:
            print(f"❌ Group structure error: {e}")
            return "Error retrieving group structure"
    
    def handle_sms_with_media(self, from_phone, message_body, media_urls):
        """CRITICAL METHOD: Main SMS handler with comprehensive logging"""
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
            if self.is_admin(from_phone) and message_body.upper().startswith(('STATS', 'HELP', 'RECENT', 'ADD ', 'GROUPS')):
                print(f"🔧 Processing admin command: {message_body}")
                return self.handle_admin_commands(from_phone, message_body)
            
            # Check for member commands (available to all)
            if message_body.upper().startswith(('GROUPS',)):
                if message_body.upper() == 'GROUPS':
                    member_groups = self.get_member_groups(from_phone)
                    if member_groups:
                        result = f"📋 YOUR GROUPS:\n\n"
                        for group in member_groups:
                            result += f"• {group['name']} (ID: {group['id']})\n"
                        return result
                    else:
                        return "❌ You are not assigned to any groups"
            
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
print("🏛️ Initializing Ultimate Church SMS System...")
broadcast_sms = MultiGroupBroadcastSMS()

def setup_your_congregation():
    """Setup your 3 existing groups with real members"""
    print("🔧 Setting up your 3 congregation groups...")
    
    try:
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
        print("📸 MMS support with automatic SMS fallback enabled!")
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
        cursor.execute("SELECT COUNT(*) FROM broadcast_messages")
        message_count = cursor.fetchone()[0]
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
✅ Application: Running (Ultimate Version)
✅ Database: Connected ({member_count} members, {group_count} groups, {message_count} messages)
{twilio_status}

🔧 ENVIRONMENT:
{chr(10).join(env_status)}
Phone: {TWILIO_PHONE_NUMBER or 'NOT SET'}

📡 ENDPOINTS:
• Webhook: /webhook/sms (for Twilio)
• Test: /test (for debugging)
• Health: / (this page)
• Status: /webhook/status (delivery tracking)

🚀 FEATURES:
• Speed-optimized MMS broadcasting
• Auto SMS fallback for failed MMS
• Comprehensive admin commands
• Real-time delivery tracking
• Enhanced error handling
• Multi-group unified messaging

👑 ADMIN COMMANDS:
• STATS - Congregation statistics
• RECENT - Recent broadcasts
• GROUPS - Group structure
• ADD +phone Name TO group - Add member
• HELP - Command help

👥 MEMBER COMMANDS:
• GROUPS - Show your groups

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
    print("🏛️ Starting Ultimate Enhanced Multi-Group Broadcast SMS System...")
    print("🚀 Speed Optimized Version for Production")
    print("🔧 Debug mode: ENABLED")
    print("📋 Comprehensive logging: ACTIVE")
    print("⚡ Fast MMS processing: ENABLED")
    print("👑 Full admin functionality: ENABLED")
    print("📊 Enhanced analytics: ENABLED")
    
    # Setup your congregation
    setup_your_congregation()
    
    print(f"\n🚀 Ultimate Church SMS System Running!")
    print(f"📱 Webhook endpoint: /webhook/sms")
    print(f"🧪 Test endpoint: /test")
    print(f"📊 Health check: /")
    print(f"📈 Status tracking: /webhook/status")
    print(f"🔍 All events logged with detailed debugging")
    print(f"📸 Speed-optimized MMS support with automatic SMS fallback")
    print(f"👑 Complete admin command suite available")
    print(f"⚡ Optimized for production performance")
    print(f"🏛️ Ready to serve your congregation!")
    
    # Use PORT environment variable for Render
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)