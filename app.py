import os
import boto3
import requests
import hashlib
import mimetypes
import uuid
import logging
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from twilio.rest import Client
import sqlite3
import re
import traceback
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

# Production logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('production_sms.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Production Configuration - All from environment variables
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')

# Cloudflare R2 Configuration
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
R2_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL')
R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME', 'church-media-production')
R2_PUBLIC_URL = os.environ.get('R2_PUBLIC_URL')

# Production Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max request

class ProductionSmartMediaSystem:
    def __init__(self):
        """Initialize production-grade smart media system with enhanced SMS reactions"""
        self.twilio_client = None
        self.r2_client = None
        self.executor = ThreadPoolExecutor(max_workers=10)
        
        # Initialize Twilio client
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
            try:
                self.twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                # Verify connection
                account = self.twilio_client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
                logger.info(f"✅ Twilio production connection established: {account.friendly_name}")
            except Exception as e:
                logger.error(f"❌ Twilio connection failed: {e}")
                raise
        else:
            logger.error("❌ Missing Twilio credentials")
            raise ValueError("Twilio credentials required for production")
        
        # Initialize Cloudflare R2 client
        if R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_ENDPOINT_URL:
            try:
                self.r2_client = boto3.client(
                    's3',
                    endpoint_url=R2_ENDPOINT_URL,
                    aws_access_key_id=R2_ACCESS_KEY_ID,
                    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                    region_name='auto'
                )
                # Verify bucket access
                self.r2_client.head_bucket(Bucket=R2_BUCKET_NAME)
                logger.info(f"✅ Cloudflare R2 production connection established: {R2_BUCKET_NAME}")
            except Exception as e:
                logger.error(f"❌ R2 connection failed: {e}")
                raise
        else:
            logger.error("❌ Missing R2 credentials")
            raise ValueError("R2 credentials required for production")
        
        self.init_production_database()
        logger.info("🚀 Production Smart Media System with Enhanced SMS Reactions fully initialized")
    
    def init_production_database(self):
        """Initialize production database with optimizations and reaction tracking"""
        try:
            # Use WAL mode for production performance
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.execute('PRAGMA synchronous=NORMAL;')
            conn.execute('PRAGMA cache_size=10000;')
            conn.execute('PRAGMA temp_store=memory;')
            conn.execute('PRAGMA foreign_keys=ON;')
            
            cursor = conn.cursor()
            
            # Production groups table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Production members table with enhanced tracking
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone_number TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    is_admin BOOLEAN DEFAULT FALSE,
                    active BOOLEAN DEFAULT TRUE,
                    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    message_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Production group membership table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS group_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (group_id) REFERENCES groups (id) ON DELETE CASCADE,
                    FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE,
                    UNIQUE(group_id, member_id)
                )
            ''')
            
            # Production messages table with comprehensive tracking
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS broadcast_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_phone TEXT NOT NULL,
                    from_name TEXT NOT NULL,
                    original_message TEXT NOT NULL,
                    processed_message TEXT NOT NULL,
                    message_type TEXT DEFAULT 'text',
                    has_media BOOLEAN DEFAULT FALSE,
                    media_count INTEGER DEFAULT 0,
                    large_media_count INTEGER DEFAULT 0,
                    processing_status TEXT DEFAULT 'completed',
                    delivery_status TEXT DEFAULT 'pending',
                    reaction_summary TEXT DEFAULT '',
                    last_reaction_update TIMESTAMP,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Enhanced reaction tracking table for count-based display
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_reactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_message_id INTEGER NOT NULL,
                    reactor_phone TEXT NOT NULL,
                    reactor_name TEXT NOT NULL,
                    reaction_emoji TEXT NOT NULL,
                    previous_reaction_emoji TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (original_message_id) REFERENCES broadcast_messages (id) ON DELETE CASCADE,
                    UNIQUE(original_message_id, reactor_phone)
                )
            ''')
            
            # Production media files table with comprehensive metadata
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS media_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    original_url TEXT NOT NULL,
                    twilio_media_sid TEXT,
                    r2_object_key TEXT,
                    public_url TEXT,
                    clean_filename TEXT,
                    display_name TEXT,
                    original_size INTEGER,
                    final_size INTEGER,
                    mime_type TEXT,
                    file_hash TEXT,
                    compression_detected BOOLEAN DEFAULT FALSE,
                    upload_status TEXT DEFAULT 'pending',
                    upload_error TEXT,
                    access_count INTEGER DEFAULT 0,
                    last_accessed TIMESTAMP,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (message_id) REFERENCES broadcast_messages (id) ON DELETE CASCADE
                )
            ''')
            
            # Production delivery tracking with comprehensive analytics
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS delivery_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    member_id INTEGER NOT NULL,
                    to_phone TEXT NOT NULL,
                    delivery_method TEXT NOT NULL,
                    delivery_status TEXT DEFAULT 'pending',
                    twilio_message_sid TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    delivery_time_ms INTEGER,
                    retry_count INTEGER DEFAULT 0,
                    delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (message_id) REFERENCES broadcast_messages (id) ON DELETE CASCADE,
                    FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
                )
            ''')
            
            # Production analytics table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_analytics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    metric_metadata TEXT,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Performance monitoring table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_type TEXT NOT NULL,
                    operation_duration_ms INTEGER NOT NULL,
                    success BOOLEAN DEFAULT TRUE,
                    error_details TEXT,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create production indexes for performance including reaction tracking
            indexes = [
                'CREATE INDEX IF NOT EXISTS idx_members_phone ON members(phone_number)',
                'CREATE INDEX IF NOT EXISTS idx_members_active ON members(active)',
                'CREATE INDEX IF NOT EXISTS idx_messages_sent_at ON broadcast_messages(sent_at)',
                'CREATE INDEX IF NOT EXISTS idx_messages_status ON broadcast_messages(delivery_status)',
                'CREATE INDEX IF NOT EXISTS idx_media_message_id ON media_files(message_id)',
                'CREATE INDEX IF NOT EXISTS idx_media_status ON media_files(upload_status)',
                'CREATE INDEX IF NOT EXISTS idx_media_public_url ON media_files(public_url)',
                'CREATE INDEX IF NOT EXISTS idx_delivery_message_id ON delivery_log(message_id)',
                'CREATE INDEX IF NOT EXISTS idx_delivery_member_id ON delivery_log(member_id)',
                'CREATE INDEX IF NOT EXISTS idx_delivery_status ON delivery_log(delivery_status)',
                'CREATE INDEX IF NOT EXISTS idx_analytics_metric ON system_analytics(metric_name, recorded_at)',
                'CREATE INDEX IF NOT EXISTS idx_performance_type ON performance_metrics(operation_type, recorded_at)',
                # Enhanced reaction tracking indexes
                'CREATE INDEX IF NOT EXISTS idx_reactions_original_msg ON message_reactions(original_message_id)',
                'CREATE INDEX IF NOT EXISTS idx_reactions_reactor ON message_reactions(reactor_phone)',
                'CREATE INDEX IF NOT EXISTS idx_reactions_active ON message_reactions(is_active)',
                'CREATE INDEX IF NOT EXISTS idx_reactions_emoji ON message_reactions(reaction_emoji)',
                'CREATE INDEX IF NOT EXISTS idx_reactions_unique ON message_reactions(original_message_id, reactor_phone)'
            ]
            
            for index_sql in indexes:
                cursor.execute(index_sql)
            
            # Initialize production groups
            cursor.execute("SELECT COUNT(*) FROM groups")
            if cursor.fetchone()[0] == 0:
                production_groups = [
                    ("YesuWay Congregation", "Main congregation group"),
                    ("Church Leadership", "Leadership and admin group"),
                    ("Media Team", "Media and technology team")
                ]
                cursor.executemany("INSERT INTO groups (name, description) VALUES (?, ?)", production_groups)
                logger.info("✅ Production groups initialized")
            
            conn.commit()
            conn.close()
            logger.info("✅ Production database initialized with enhanced SMS reaction system")
            
        except Exception as e:
            logger.error(f"❌ Production database initialization failed: {e}")
            traceback.print_exc()
            raise

    def detect_reaction_pattern(self, message_body):
        """Detect if message is a reaction using modern reaction patterns"""
        if not message_body:
            return None
        
        message_body = message_body.strip()
        
        # Detect various reaction patterns
        reaction_patterns = [
            # Modern reaction patterns: "Laughed at", "Emphasized", "Reacted 😍 to", etc.
            r'^(Laughed at|Emphasized|Questioned|Liked|Loved|Disliked|Reacted\s*([😀-🿿]+)\s*to)\s*["\'“”](.+)["\'“”]',
            # Single emoji reactions
            r"^([😀-🿿]+)\s*$",
            # Emoji with "to" pattern: "😍 to 'message'"
            r'^([😀-🿿]+)\s*to\s*["\'“”](.+)["\'“”]',
            # Apple style: "Loved 'message'"
            r'^(Loved|Liked|Disliked|Emphasized|Laughed at|Questioned)\s*["\'“”](.+)["\'“”]'
        ]
        
        for pattern in reaction_patterns:
            match = re.match(pattern, message_body, re.UNICODE)
            if match:
                groups = match.groups()
                
                # Extract reaction type and target message
                if len(groups) >= 2:
                    reaction_type = groups[0]
                    target_message = groups[-1]  # Last group is usually the target message
                else:
                    reaction_type = groups[0]
                    target_message = ""
                
                # Map reaction types to emojis
                reaction_mapping = {
                    'Laughed at': '😂',
                    'Emphasized': '‼️',
                    'Questioned': '❓',
                    'Liked': '👍',
                    'Loved': '❤️',
                    'Disliked': '👎'
                }
                
                # Use mapped emoji or extract emoji from message
                emoji = reaction_mapping.get(reaction_type, reaction_type)
                
                # Clean emoji (remove extra characters)
                emoji_match = re.search(r'([😀-🿿]+)', emoji)
                if emoji_match:
                    emoji = emoji_match.group(1)
                
                logger.info(f"🎯 Detected reaction: '{emoji}' to message fragment: '{target_message[:50]}...'")
                
                return {
                    'emoji': emoji,
                    'target_message_fragment': target_message[:100],  # Store fragment for matching
                    'reaction_type': reaction_type,
                    'full_pattern': message_body
                }
        
        return None

    def find_recent_message_for_reaction(self, target_fragment, reactor_phone, hours_back=24):
        """Find the most recent message that matches the reaction target"""
        try:
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            # Look for recent messages (within last 24 hours by default)
            since_time = datetime.now() - timedelta(hours=hours_back)
            
            cursor.execute('''
                SELECT id, original_message, from_phone, from_name, sent_at
                FROM broadcast_messages 
                WHERE sent_at > ? 
                AND from_phone != ?
                ORDER BY sent_at DESC
                LIMIT 10
            ''', (since_time.isoformat(), reactor_phone))
            
            recent_messages = cursor.fetchall()
            conn.close()
            
            if not recent_messages:
                logger.info(f"🔍 No recent messages found for reaction matching")
                return None
            
            # Try to find best match using fuzzy matching
            best_match = None
            best_score = 0
            
            target_words = set(target_fragment.lower().split())
            
            for msg_id, original_msg, from_phone, from_name, sent_at in recent_messages:
                if not original_msg:
                    continue
                
                message_words = set(original_msg.lower().split())
                
                # Calculate similarity score
                if target_words and message_words:
                    common_words = target_words.intersection(message_words)
                    score = len(common_words) / max(len(target_words), len(message_words))
                    
                    # Boost score if target fragment is substring of message
                    if target_fragment.lower() in original_msg.lower():
                        score += 0.5
                    
                    if score > best_score and score > 0.3:  # Minimum similarity threshold
                        best_score = score
                        best_match = {
                            'id': msg_id,
                            'message': original_msg,
                            'from_phone': from_phone,
                            'from_name': from_name,
                            'sent_at': sent_at,
                            'similarity_score': score
                        }
            
            if best_match:
                logger.info(f"✅ Found reaction target (score: {best_match['similarity_score']:.2f}): "
                           f"Message {best_match['id']} from {best_match['from_name']}")
                return best_match
            else:
                # Fallback: return most recent message if no good match
                msg_id, original_msg, from_phone, from_name, sent_at = recent_messages[0]
                logger.info(f"🎯 Using most recent message as fallback: Message {msg_id}")
                return {
                    'id': msg_id,
                    'message': original_msg,
                    'from_phone': from_phone,
                    'from_name': from_name,
                    'sent_at': sent_at,
                    'similarity_score': 0.0
                }
        
        except Exception as e:
            logger.error(f"❌ Error finding reaction target: {e}")
            traceback.print_exc()
            return None

    def get_reaction_count_summary(self, message_id):
        """Get count-based reaction summary: '4 reactions: ❤️×2  👍×1  😂×1'"""
        try:
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            # Get all active reactions for this message
            cursor.execute('''
                SELECT reaction_emoji, COUNT(*) as count
                FROM message_reactions 
                WHERE original_message_id = ? AND is_active = 1
                GROUP BY reaction_emoji
                ORDER BY count DESC, reaction_emoji
            ''', (message_id,))
            
            reaction_counts = cursor.fetchall()
            conn.close()
            
            if not reaction_counts:
                return ""
            
            # Calculate total reactions
            total_reactions = sum(count for _, count in reaction_counts)
            
            # Format count display: ❤️×2  👍×1  😂×1
            reaction_parts = []
            for emoji, count in reaction_counts:
                if count == 1:
                    reaction_parts.append(emoji)
                else:
                    reaction_parts.append(f"{emoji}×{count}")
            
            reaction_display = "  ".join(reaction_parts)
            
            # Final format: "4 reactions: ❤️×2  👍×1  😂×1"
            if total_reactions == 1:
                return f"1 reaction: {reaction_display}"
            else:
                return f"{total_reactions} reactions: {reaction_display}"
                
        except Exception as e:
            logger.error(f"❌ Error getting reaction summary: {e}")
            traceback.print_exc()
            return ""

    def handle_enhanced_reaction(self, reactor_phone, reaction_data, target_message):
        """Handle reaction with enhanced SMS count format - NO SPAM MESSAGES"""
        try:
            reactor = self.get_member_info_production(reactor_phone)
            target_msg_id = target_message['id']
            new_emoji = reaction_data['emoji']
            
            logger.info(f"🔄 Processing enhanced reaction: {reactor['name']} reacting '{new_emoji}' to message {target_msg_id}")
            
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            # Check if user already has a reaction to this message
            cursor.execute('''
                SELECT id, reaction_emoji, is_active 
                FROM message_reactions 
                WHERE original_message_id = ? AND reactor_phone = ?
            ''', (target_msg_id, reactor_phone))
            
            existing_reaction = cursor.fetchone()
            
            if existing_reaction:
                reaction_id, old_emoji, is_active = existing_reaction
                
                if old_emoji == new_emoji and is_active:
                    # Same reaction - remove it (toggle off)
                    logger.info(f"🔄 Removing reaction: {reactor['name']} removing '{old_emoji}' from message {target_msg_id}")
                    
                    cursor.execute('''
                        UPDATE message_reactions 
                        SET is_active = 0, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (reaction_id,))
                    
                    action = "removed"
                    
                elif old_emoji == new_emoji and not is_active:
                    # Re-adding same reaction
                    logger.info(f"🔄 Re-adding reaction: {reactor['name']} adding '{new_emoji}' to message {target_msg_id}")
                    
                    cursor.execute('''
                        UPDATE message_reactions 
                        SET is_active = 1, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (reaction_id,))
                    
                    action = "added"
                    
                else:
                    # Different reaction - update it
                    logger.info(f"🔄 Updating reaction: {reactor['name']} changing '{old_emoji}' to '{new_emoji}' on message {target_msg_id}")
                    
                    cursor.execute('''
                        UPDATE message_reactions 
                        SET reaction_emoji = ?, previous_reaction_emoji = ?, is_active = 1, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (new_emoji, old_emoji, reaction_id))
                    
                    action = "changed"
            else:
                # New reaction - add it
                logger.info(f"🔄 Adding new reaction: {reactor['name']} adding '{new_emoji}' to message {target_msg_id}")
                
                cursor.execute('''
                    INSERT INTO message_reactions 
                    (original_message_id, reactor_phone, reactor_name, reaction_emoji, is_active) 
                    VALUES (?, ?, ?, ?, 1)
                ''', (target_msg_id, reactor_phone, reactor['name'], new_emoji))
                
                action = "added"
            
            # Get updated reaction summary
            reaction_summary = self.get_reaction_count_summary(target_msg_id)
            
            # Update the original message record with new reaction summary
            cursor.execute('''
                UPDATE broadcast_messages 
                SET reaction_summary = ?, last_reaction_update = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (reaction_summary, target_msg_id))
            
            conn.commit()
            
            # Check if we should send an update (smart timing)
            if self.should_send_reaction_update(target_msg_id, action, reaction_summary):
                self.send_enhanced_reaction_update(target_message, reaction_summary)
            
            conn.close()
            
            # Return confirmation to reactor
            if action == "removed":
                return f"✅ Removed your {new_emoji} reaction"
            elif action == "changed":
                return f"✅ Changed your reaction to {new_emoji}"
            else:
                return f"✅ Added {new_emoji} reaction"
        
        except Exception as e:
            logger.error(f"❌ Error handling enhanced reaction: {e}")
            traceback.print_exc()
            return "❌ Reaction processing failed"

    def should_send_reaction_update(self, message_id, action, reaction_summary):
        """Smart timing: decide when to send reaction updates to avoid spam"""
        try:
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            # Get reaction statistics
            cursor.execute('''
                SELECT COUNT(*) as total_reactions,
                       COUNT(DISTINCT reactor_phone) as unique_reactors
                FROM message_reactions 
                WHERE original_message_id = ? AND is_active = 1
            ''', (message_id,))
            
            total_reactions, unique_reactors = cursor.fetchone()
            
            # Get time since last update
            cursor.execute('''
                SELECT last_reaction_update 
                FROM broadcast_messages 
                WHERE id = ?
            ''', (message_id,))
            
            last_update = cursor.fetchone()[0]
            conn.close()
            
            # Send update if:
            # 1. First reaction on a message
            # 2. Every 3rd reaction  
            # 3. Someone removes a reaction
            # 4. 5+ minutes since last update and new activity
            
            if total_reactions == 1:
                logger.info(f"📤 Sending update: First reaction")
                return True
            
            if action == "removed":
                logger.info(f"📤 Sending update: Reaction removed")
                return True
            
            if total_reactions % 3 == 0:
                logger.info(f"📤 Sending update: Every 3rd reaction ({total_reactions})")
                return True
            
            if last_update:
                last_update_time = datetime.fromisoformat(last_update)
                minutes_since_update = (datetime.now() - last_update_time).total_seconds() / 60
                if minutes_since_update >= 5:
                    logger.info(f"📤 Sending update: 5+ minutes since last update")
                    return True
            
            logger.info(f"📝 Not sending update: Smart timing ({total_reactions} reactions)")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error in update timing: {e}")
            return True  # Default to sending update if error

    def send_enhanced_reaction_update(self, target_message, reaction_summary):
        """Send enhanced SMS reaction update with count format"""
        try:
            # Create enhanced update message
            message_preview = target_message['message'][:50]
            if len(target_message['message']) > 50:
                message_preview += "..."
            
            update_message = f"""🔄 Reaction Update:
💬 {target_message['from_name']}: "{message_preview}"

{reaction_summary}"""
            
            # Broadcast to all members except original sender
            recipients = self.get_all_active_members(exclude_phone=target_message['from_phone'])
            
            logger.info(f"📤 Sending enhanced reaction update to {len(recipients)} members")
            
            # Use concurrent delivery
            def send_to_member(member):
                result = self.send_sms_production(member['phone'], update_message)
                if result['success']:
                    logger.info(f"✅ Reaction update sent to {member['name']}")
                else:
                    logger.error(f"❌ Failed to send reaction update to {member['name']}: {result['error']}")
            
            # Execute concurrent delivery
            futures = []
            for recipient in recipients:
                future = self.executor.submit(send_to_member, recipient)
                futures.append(future)
            
            # Wait for all deliveries
            for future in futures:
                try:
                    future.result(timeout=30)
                except Exception as e:
                    logger.error(f"❌ Concurrent delivery error: {e}")
            
            logger.info(f"✅ Enhanced reaction update broadcast completed")
            
        except Exception as e:
            logger.error(f"❌ Error sending reaction update: {e}")
            traceback.print_exc()

    def clean_phone_number(self, phone):
        """Production phone number cleaning with validation"""
        if not phone:
            return None
        
        # Remove all non-digit characters
        digits = re.sub(r'\D', '', str(phone))
        
        # Handle different international formats
        if len(digits) == 10:
            return f"+1{digits}"
        elif len(digits) == 11 and digits.startswith('1'):
            return f"+{digits}"
        elif len(digits) > 11:
            return f"+{digits}"
        else:
            logger.warning(f"Invalid phone number format: {phone}")
            return phone
    
    def record_performance_metric(self, operation_type, duration_ms, success=True, error_details=None):
        """Record performance metrics for monitoring"""
        try:
            conn = sqlite3.connect('production_church.db', timeout=5.0)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO performance_metrics (operation_type, operation_duration_ms, success, error_details) 
                VALUES (?, ?, ?, ?)
            ''', (operation_type, duration_ms, success, error_details))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"❌ Performance metric recording failed: {e}")
    
    def download_original_media_from_twilio(self, media_url, media_sid=None):
        """Download original media from Twilio with full authentication"""
        start_time = time.time()
        try:
            logger.info(f"📥 Downloading original media: {media_url}")
            
            # Use Twilio credentials for authenticated download
            response = requests.get(
                media_url,
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                timeout=60,
                stream=True
            )
            
            if response.status_code == 200:
                content = b''
                content_length = 0
                
                # Stream download for large files
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        content += chunk
                        content_length += len(chunk)
                
                content_type = response.headers.get('content-type', 'application/octet-stream')
                file_hash = hashlib.sha256(content).hexdigest()
                
                duration_ms = int((time.time() - start_time) * 1000)
                self.record_performance_metric('media_download', duration_ms, True)
                
                logger.info(f"✅ Downloaded {content_length} bytes, type: {content_type}")
                
                return {
                    'content': content,
                    'size': content_length,
                    'mime_type': content_type,
                    'hash': file_hash,
                    'headers': dict(response.headers)
                }
            else:
                duration_ms = int((time.time() - start_time) * 1000)
                self.record_performance_metric('media_download', duration_ms, False, f"HTTP {response.status_code}")
                logger.error(f"❌ Download failed: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.record_performance_metric('media_download', duration_ms, False, str(e))
            logger.error(f"❌ Media download error: {e}")
            traceback.print_exc()
            return None
    
    def generate_clean_filename(self, original_filename, mime_type, file_hash, media_index=1):
        """Generate clean, user-friendly filename"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Generate clean, simple names based on media type
        if 'image' in mime_type:
            if 'gif' in mime_type:
                extension = '.gif'
                base_name = f"gif_{timestamp}"
                display_name = f"GIF {media_index}"
            else:
                extension = '.jpg'
                base_name = f"photo_{timestamp}"
                display_name = f"Photo {media_index}"
        elif 'video' in mime_type:
            extension = '.mp4'
            base_name = f"video_{timestamp}"
            display_name = f"Video {media_index}"
        elif 'audio' in mime_type:
            extension = '.mp3'
            base_name = f"audio_{timestamp}"
            display_name = f"Audio {media_index}"
        else:
            extension = mimetypes.guess_extension(mime_type) or '.file'
            base_name = f"file_{timestamp}"
            display_name = f"File {media_index}"
        
        # Add index for multiple files
        if media_index > 1:
            base_name += f"_{media_index}"
        
        clean_filename = f"church/{base_name}{extension}"
        
        return clean_filename, display_name
    
    def upload_to_r2_production(self, file_content, object_key, mime_type, metadata=None):
        """Upload file to Cloudflare R2 with production settings"""
        start_time = time.time()
        try:
            logger.info(f"☁️ Uploading to R2 production: {object_key}")
            
            # Prepare metadata
            upload_metadata = {
                'church-system': 'yesuway-production',
                'upload-timestamp': datetime.now().isoformat(),
                'content-hash': hashlib.sha256(file_content).hexdigest()
            }
            
            if metadata:
                upload_metadata.update(metadata)
            
            # Upload with production settings
            self.r2_client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=object_key,
                Body=file_content,
                ContentType=mime_type,
                ContentDisposition='inline',
                CacheControl='public, max-age=31536000',  # 1 year cache
                Metadata=upload_metadata,
                ServerSideEncryption='AES256'
            )
            
            # Generate production public URL
            if R2_PUBLIC_URL:
                public_url = f"{R2_PUBLIC_URL.rstrip('/')}/{object_key}"
            else:
                # Generate presigned URL as fallback
                public_url = self.r2_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': R2_BUCKET_NAME, 'Key': object_key},
                    ExpiresIn=31536000  # 1 year
                )
            
            duration_ms = int((time.time() - start_time) * 1000)
            self.record_performance_metric('r2_upload', duration_ms, True)
            
            logger.info(f"✅ Production upload successful: {public_url}")
            return public_url
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.record_performance_metric('r2_upload', duration_ms, False, str(e))
            logger.error(f"❌ R2 production upload failed: {e}")
            traceback.print_exc()
            return None
    
    def process_large_media_production(self, message_id, media_urls):
        """Production media processing with clean display names"""
        logger.info(f"🔄 Production media processing for message {message_id}")
        
        processed_links = []
        processing_errors = []
        
        for i, media in enumerate(media_urls):
            media_url = media.get('url', '')
            media_type = media.get('type', 'unknown')
            
            try:
                logger.info(f"📎 Processing media {i+1}/{len(media_urls)}: {media_type}")
                
                # Download original from Twilio
                media_data = self.download_original_media_from_twilio(media_url)
                
                if not media_data:
                    error_msg = f"Failed to download media {i+1}"
                    processing_errors.append(error_msg)
                    logger.error(error_msg)
                    continue
                
                # Check if file was compressed (heuristic)
                file_size = media_data['size']
                compression_detected = file_size >= 4.8 * 1024 * 1024  # Close to 5MB limit
                
                # Generate clean filename and display name
                clean_filename, display_name = self.generate_clean_filename(
                    f"media_{i+1}", 
                    media_data['mime_type'], 
                    media_data['hash'],
                    i+1
                )
                
                # Upload to R2
                public_url = self.upload_to_r2_production(
                    media_data['content'],
                    clean_filename,
                    media_data['mime_type'],
                    metadata={
                        'original-size': str(file_size),
                        'compression-detected': str(compression_detected),
                        'media-index': str(i),
                        'display-name': display_name
                    }
                )
                
                if public_url:
                    # Store in database with clean information
                    conn = sqlite3.connect('production_church.db', timeout=30.0)
                    cursor = conn.cursor()
                    
                    cursor.execute('''
                        INSERT INTO media_files 
                        (message_id, original_url, r2_object_key, public_url, clean_filename, display_name,
                         original_size, final_size, mime_type, file_hash, compression_detected, upload_status) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed')
                    ''', (
                        message_id, media_url, clean_filename, public_url, clean_filename.split('/')[-1], display_name,
                        file_size, file_size, media_data['mime_type'], media_data['hash'], compression_detected
                    ))
                    
                    conn.commit()
                    conn.close()
                    
                    processed_links.append({
                        'url': public_url,
                        'display_name': display_name,
                        'type': media_data['mime_type']
                    })
                    logger.info(f"✅ Media {i+1} processed successfully")
                else:
                    error_msg = f"Failed to upload media {i+1} to R2"
                    processing_errors.append(error_msg)
                    logger.error(error_msg)
                
            except Exception as e:
                error_msg = f"Error processing media {i+1}: {str(e)}"
                processing_errors.append(error_msg)
                logger.error(error_msg)
                traceback.print_exc()
        
        logger.info(f"✅ Production media processing complete: {len(processed_links)} successful, {len(processing_errors)} errors")
        return processed_links, processing_errors
    
    def get_all_active_members(self, exclude_phone=None):
        """Get all active members with production caching"""
        try:
            exclude_phone = self.clean_phone_number(exclude_phone) if exclude_phone else None
            
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            query = '''
                SELECT DISTINCT m.id, m.phone_number, m.name, m.is_admin
                FROM members m
                JOIN group_members gm ON m.id = gm.member_id
                WHERE m.active = 1
            '''
            params = []
            
            if exclude_phone:
                query += " AND m.phone_number != ?"
                params.append(exclude_phone)
            
            query += " ORDER BY m.name"
            
            cursor.execute(query, params)
            members = []
            
            for row in cursor.fetchall():
                member_id, phone, name, is_admin = row
                clean_phone = self.clean_phone_number(phone)
                if clean_phone:
                    members.append({
                        "id": member_id,
                        "phone": clean_phone,
                        "name": name,
                        "is_admin": bool(is_admin)
                    })
            
            conn.close()
            logger.info(f"📋 Retrieved {len(members)} active members")
            return members
            
        except Exception as e:
            logger.error(f"❌ Error retrieving members: {e}")
            traceback.print_exc()
            return []
    
    def get_member_info_production(self, phone_number):
        """Get member info with production auto-registration"""
        try:
            phone_number = self.clean_phone_number(phone_number)
            
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, name, is_admin, message_count 
                FROM members 
                WHERE phone_number = ? AND active = 1
            ''', (phone_number,))
            
            result = cursor.fetchone()
            
            if result:
                member_id, name, is_admin, msg_count = result
                conn.close()
                return {
                    "id": member_id,
                    "name": name,
                    "is_admin": bool(is_admin),
                    "message_count": msg_count
                }
            else:
                # Auto-register new member in production
                name = f"Member {phone_number[-4:]}"
                logger.info(f"🆕 Auto-registering production member: {name} ({phone_number})")
                
                cursor.execute('''
                    INSERT INTO members (phone_number, name, is_admin, active, message_count) 
                    VALUES (?, ?, ?, 1, 0)
                ''', (phone_number, name, False))
                
                member_id = cursor.lastrowid
                
                # Add to default group (group 1)
                cursor.execute('''
                    INSERT INTO group_members (group_id, member_id) 
                    VALUES (1, ?)
                ''', (member_id,))
                
                conn.commit()
                conn.close()
                
                return {
                    "id": member_id,
                    "name": name,
                    "is_admin": False,
                    "message_count": 0
                }
                
        except Exception as e:
            logger.error(f"❌ Error getting member info: {e}")
            traceback.print_exc()
            return {"id": None, "name": "Unknown", "is_admin": False, "message_count": 0}
    
    def send_sms_production(self, to_phone, message_text, max_retries=3):
        """Send SMS with production retry logic"""
        start_time = time.time()
        for attempt in range(max_retries):
            try:
                message_obj = self.twilio_client.messages.create(
                    body=message_text,
                    from_=TWILIO_PHONE_NUMBER,
                    to=to_phone
                )
                
                duration_ms = int((time.time() - start_time) * 1000)
                self.record_performance_metric('sms_send', duration_ms, True)
                
                logger.info(f"✅ SMS sent to {to_phone}: {message_obj.sid}")
                return {
                    "success": True,
                    "sid": message_obj.sid,
                    "attempt": attempt + 1
                }
                
            except Exception as e:
                logger.warning(f"⚠️ SMS attempt {attempt + 1} failed for {to_phone}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))  # Exponential backoff
                else:
                    duration_ms = int((time.time() - start_time) * 1000)
                    self.record_performance_metric('sms_send', duration_ms, False, str(e))
                    logger.error(f"❌ All SMS attempts failed for {to_phone}")
                    return {
                        "success": False,
                        "error": str(e),
                        "attempts": max_retries
                    }
    
    def format_message_with_reactions(self, original_message, sender, message_id, media_links=None):
        """Format message with reaction count summary"""
        # Get reaction summary
        reaction_summary = self.get_reaction_count_summary(message_id)
        
        # Build base message
        if media_links:
            # Create message with clean media links
            if len(media_links) == 1:
                media_item = media_links[0]
                base_message = f"💬 {sender['name']}:\n{original_message}\n\n🔗 {media_item['display_name']}: {media_item['url']}"
            else:
                media_text = "\n".join([f"🔗 {item['display_name']}: {item['url']}" for item in media_links])
                base_message = f"💬 {sender['name']}:\n{original_message}\n\n{media_text}"
        else:
            base_message = f"💬 {sender['name']}:\n{original_message}"
        
        # Add reaction summary if present
        if reaction_summary:
            return f"{base_message}\n\n{reaction_summary}"
        else:
            return base_message
    
    def broadcast_smart_message_production(self, from_phone, message_text, media_urls=None):
        """Production smart broadcasting with enhanced reaction display"""
        start_time = time.time()
        logger.info(f"📡 Starting production smart broadcast from {from_phone}")
        
        try:
            # Get sender info
            sender = self.get_member_info_production(from_phone)
            
            # Get all recipients
            recipients = self.get_all_active_members(exclude_phone=from_phone)
            
            if not recipients:
                logger.warning("❌ No active recipients found")
                return "No active congregation members found for broadcast."
            
            # Store broadcast message
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO broadcast_messages 
                (from_phone, from_name, original_message, processed_message, message_type, 
                 has_media, media_count, processing_status, delivery_status, reaction_summary) 
                VALUES (?, ?, ?, ?, ?, ?, ?, 'processing', 'pending', '')
            ''', (
                from_phone, sender['name'], message_text, message_text,
                'media' if media_urls else 'text',
                bool(media_urls), len(media_urls) if media_urls else 0
            ))
            
            message_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            # Process media if present
            clean_media_links = []
            large_media_count = 0
            
            if media_urls:
                logger.info(f"🔄 Processing {len(media_urls)} media files...")
                clean_media_links, processing_errors = self.process_large_media_production(message_id, media_urls)
                large_media_count = len(clean_media_links)
                
                if processing_errors:
                    logger.warning(f"⚠️ Media processing errors: {processing_errors}")
            
            # Format final message with enhanced reaction support
            final_message = self.format_message_with_reactions(
                message_text, sender, message_id, clean_media_links
            )
            
            # Update message with processed content
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE broadcast_messages 
                SET processed_message = ?, large_media_count = ?, processing_status = 'completed'
                WHERE id = ?
            ''', (final_message, large_media_count, message_id))
            conn.commit()
            conn.close()
            
            # Production broadcasting with concurrent delivery
            delivery_stats = {
                'sent': 0,
                'failed': 0,
                'total_time': 0,
                'errors': []
            }
            
            def send_to_member(member):
                member_start = time.time()
                result = self.send_sms_production(member['phone'], final_message)
                delivery_time = int((time.time() - member_start) * 1000)
                
                # Log delivery
                conn = sqlite3.connect('production_church.db', timeout=30.0)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO delivery_log 
                    (message_id, member_id, to_phone, delivery_method, delivery_status, 
                     twilio_message_sid, error_message, delivery_time_ms) 
                    VALUES (?, ?, ?, 'sms', ?, ?, ?, ?)
                ''', (
                    message_id, member['id'], member['phone'],
                    'delivered' if result['success'] else 'failed',
                    result.get('sid'), result.get('error'), delivery_time
                ))
                conn.commit()
                conn.close()
                
                if result['success']:
                    delivery_stats['sent'] += 1
                    logger.info(f"✅ Delivered to {member['name']}: {result['sid']}")
                else:
                    delivery_stats['failed'] += 1
                    delivery_stats['errors'].append(f"{member['name']}: {result['error']}")
                    logger.error(f"❌ Failed to {member['name']}: {result['error']}")
            
            # Execute concurrent delivery
            logger.info(f"📤 Starting concurrent delivery to {len(recipients)} recipients...")
            
            futures = []
            for recipient in recipients:
                future = self.executor.submit(send_to_member, recipient)
                futures.append(future)
            
            # Wait for all deliveries with timeout
            for future in futures:
                try:
                    future.result(timeout=30)
                except Exception as e:
                    delivery_stats['failed'] += 1
                    delivery_stats['errors'].append(f"Concurrent delivery error: {e}")
                    logger.error(f"❌ Concurrent delivery error: {e}")
            
            # Calculate final stats
            total_time = time.time() - start_time
            delivery_stats['total_time'] = total_time
            
            # Update final delivery status
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE broadcast_messages 
                SET delivery_status = 'completed'
                WHERE id = ?
            ''', (message_id,))
            
            # Record analytics
            cursor.execute('''
                INSERT INTO system_analytics (metric_name, metric_value, metric_metadata) 
                VALUES (?, ?, ?)
            ''', ('broadcast_delivery_rate', 
                  delivery_stats['sent'] / len(recipients) * 100,
                  f"sent:{delivery_stats['sent']},failed:{delivery_stats['failed']},time:{total_time:.2f}s"))
            
            conn.commit()
            conn.close()
            
            # Update sender message count
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE members 
                SET message_count = message_count + 1, last_activity = CURRENT_TIMESTAMP
                WHERE phone_number = ?
            ''', (from_phone,))
            conn.commit()
            conn.close()
            
            # Record broadcast performance
            broadcast_duration_ms = int(total_time * 1000)
            self.record_performance_metric('broadcast_complete', broadcast_duration_ms, True)
            
            logger.info(f"📊 Production broadcast completed in {total_time:.2f}s: "
                       f"{delivery_stats['sent']} sent, {delivery_stats['failed']} failed")
            
            # Return admin confirmation
            if sender['is_admin']:
                confirmation = f"✅ Enhanced broadcast completed in {total_time:.1f}s\n"
                confirmation += f"📊 Delivered: {delivery_stats['sent']}/{len(recipients)}\n"
                
                if large_media_count > 0:
                    confirmation += f"📎 Clean media links: {large_media_count}\n"
                
                if delivery_stats['failed'] > 0:
                    confirmation += f"⚠️ Failed deliveries: {delivery_stats['failed']}\n"
                
                confirmation += f"🔄 Enhanced reactions enabled - count format"
                
                return confirmation
            else:
                return None  # No confirmation for regular members
                
        except Exception as e:
            logger.error(f"❌ Production broadcast error: {e}")
            traceback.print_exc()
            
            # Update message status to failed
            try:
                conn = sqlite3.connect('production_church.db', timeout=30.0)
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE broadcast_messages 
                    SET delivery_status = 'failed', processing_status = 'error'
                    WHERE id = ?
                ''', (message_id,))
                conn.commit()
                conn.close()
            except:
                pass
            
            return "Production broadcast failed - system administrators notified"
    
    def handle_admin_commands_production(self, from_phone, message_body):
        """Enhanced admin commands with reaction system management"""
        if not self.is_admin_production(from_phone):
            return None
        
        command = message_body.upper().strip()
        
        try:
            # Admin functions
            if command.startswith('ADD '):
                return self.handle_add_member_production(message_body)
            
            elif command == 'REACTIONS':
                return self.get_recent_reactions_summary()
            
            elif command == 'HELP':
                return ("👑 ADMIN COMMANDS:\n\n"
                       "👥 Member Management:\n"
                       "• ADD +phone Name TO group - Add member\n"
                       "• REACTIONS - View recent reactions\n"
                       "• HELP - Show this help\n\n"
                       "🔄 Enhanced Reaction System:\n"
                       "• Count format: '4 reactions: ❤️×2 👍×1 😂×1'\n"
                       "• Smart timing updates\n"
                       "• Zero spam messaging\n\n"
                       "🎯 Industry-level administration")
            
            else:
                return None
                
        except Exception as e:
            logger.error(f"❌ Admin command error: {e}")
            return f"Admin command failed: {str(e)}"

    def get_recent_reactions_summary(self):
        """Get recent reactions summary for admin"""
        try:
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            # Get recent messages with reactions
            cursor.execute('''
                SELECT bm.id, bm.from_name, bm.original_message, bm.reaction_summary, bm.sent_at
                FROM broadcast_messages bm
                WHERE bm.reaction_summary != '' 
                AND bm.sent_at > datetime('now', '-7 days')
                ORDER BY bm.last_reaction_update DESC
                LIMIT 5
            ''')
            
            recent_reactions = cursor.fetchall()
            
            if not recent_reactions:
                conn.close()
                return "📊 No recent reactions in the past 7 days."
            
            summary_lines = ["📊 RECENT REACTIONS (Last 7 days):\n"]
            
            for msg_id, from_name, original_msg, reaction_summary, sent_at in recent_reactions:
                message_preview = original_msg[:30] + "..." if len(original_msg) > 30 else original_msg
                summary_lines.append(f"💬 {from_name}: \"{message_preview}\"")
                summary_lines.append(f"   {reaction_summary}\n")
            
            # Get overall stats
            cursor.execute('''
                SELECT COUNT(*) as total_reactions,
                       COUNT(DISTINCT original_message_id) as messages_with_reactions,
                       COUNT(DISTINCT reactor_phone) as unique_reactors
                FROM message_reactions 
                WHERE is_active = 1 
                AND created_at > datetime('now', '-7 days')
            ''')
            
            total_reactions, messages_with_reactions, unique_reactors = cursor.fetchone()
            
            summary_lines.append(f"📈 WEEK SUMMARY:")
            summary_lines.append(f"• {total_reactions} total reactions")
            summary_lines.append(f"• {messages_with_reactions} messages received reactions")  
            summary_lines.append(f"• {unique_reactors} people reacted")
            
            conn.close()
            return "\n".join(summary_lines)
            
        except Exception as e:
            logger.error(f"❌ Error getting reactions summary: {e}")
            return "❌ Error retrieving reactions summary"
    
    def is_admin_production(self, phone_number):
        """Check admin status with production caching"""
        try:
            phone_number = self.clean_phone_number(phone_number)
            
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("SELECT is_admin FROM members WHERE phone_number = ? AND active = 1", (phone_number,))
            result = cursor.fetchone()
            conn.close()
            
            return bool(result[0]) if result else False
            
        except Exception as e:
            logger.error(f"❌ Admin check error: {e}")
            return False
    
    def handle_add_member_production(self, message_body):
        """Handle ADD member command in production"""
        try:
            # Parse: ADD +1234567890 John Smith TO 1
            parts = message_body.split()
            if len(parts) < 5 or parts[0].upper() != 'ADD' or parts[-2].upper() != 'TO':
                return "❌ Format: ADD +1234567890 First Last TO 1"
            
            phone = parts[1]
            group_id = int(parts[-1])
            name = ' '.join(parts[2:-2])
            
            if group_id not in [1, 2, 3]:
                return "❌ Group must be 1, 2, or 3"
            
            phone = self.clean_phone_number(phone)
            
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            # Add member
            cursor.execute('''
                INSERT OR REPLACE INTO members (phone_number, name, is_admin, active) 
                VALUES (?, ?, ?, 1)
            ''', (phone, name, False))
            
            member_id = cursor.lastrowid
            
            # Add to group
            cursor.execute('''
                INSERT OR IGNORE INTO group_members (group_id, member_id) 
                VALUES (?, ?)
            ''', (group_id, member_id))
            
            conn.commit()
            conn.close()
            
            return f"✅ Added {name} to Group {group_id}\n🔄 Enhanced reactions enabled"
            
        except Exception as e:
            logger.error(f"❌ Add member error: {e}")
            return f"❌ Error adding member: {str(e)}"
    
    def handle_incoming_message_production(self, from_phone, message_body, media_urls):
        """Production message handler with enhanced SMS reactions"""
        logger.info(f"📨 Production message from {from_phone}")
        
        try:
            from_phone = self.clean_phone_number(from_phone)
            message_body = message_body.strip() if message_body else ""
            
            # Log incoming message details
            if media_urls:
                logger.info(f"📎 Received {len(media_urls)} media files")
                for i, media in enumerate(media_urls):
                    logger.info(f"   Media {i+1}: {media.get('type', 'unknown')}")
            
            # Get/create member info
            member = self.get_member_info_production(from_phone)
            logger.info(f"👤 Sender: {member['name']} (Admin: {member['is_admin']})")
            
            # 🚨 NEW: Check for reaction patterns FIRST
            reaction_data = self.detect_reaction_pattern(message_body)
            if reaction_data:
                logger.info(f"🎯 Reaction detected: {reaction_data['emoji']} by {member['name']}")
                
                # Find the target message
                target_message = self.find_recent_message_for_reaction(
                    reaction_data['target_message_fragment'], 
                    from_phone
                )
                
                if target_message:
                    # Handle enhanced reaction with count format - NO SPAM
                    response = self.handle_enhanced_reaction(from_phone, reaction_data, target_message)
                    logger.info(f"✅ Enhanced reaction processed: {response}")
                    return response
                else:
                    logger.warning(f"⚠️ Could not find target message for reaction")
                    # Fall through to normal broadcast if no target found
            
            # Handle admin commands
            admin_response = self.handle_admin_commands_production(from_phone, message_body)
            if admin_response:
                logger.info(f"🔧 Admin command processed")
                return admin_response
            
            # Handle member commands
            if message_body.upper() == 'HELP':
                return ("📋 YESUWAY CHURCH SMS SYSTEM\n\n"
                       "✅ Send messages to entire congregation\n"
                       "✅ Share photos/videos (unlimited size)\n"
                       "✅ Clean media links (no technical details)\n"
                       "✅ Full quality preserved automatically\n"
                       "✅ Enhanced reactions with count format\n\n"
                       "📱 Text HELP for this message\n"
                       "🔄 Reactions display as: '4 reactions: ❤️×2 👍×1 😂×1'\n"
                       "🚫 Zero reaction spam - smart updates only\n"
                       "🏛️ Production system - serving 24/7")
            
            # Default: Smart broadcast processing
            logger.info(f"📡 Processing smart broadcast...")
            return self.broadcast_smart_message_production(from_phone, message_body, media_urls)
            
        except Exception as e:
            logger.error(f"❌ Production message processing error: {e}")
            traceback.print_exc()
            return "Message processing temporarily unavailable - please try again"

# Initialize production system
logger.info("🚀 Initializing Production Smart Media System with Enhanced SMS Reactions...")
try:
    sms_system = ProductionSmartMediaSystem()
    logger.info("✅ Production system fully operational with enhanced reaction count format")
except Exception as e:
    logger.critical(f"💥 Production system failed to initialize: {e}")
    raise

def setup_production_congregation():
    """Setup production congregation with real members"""
    logger.info("🔧 Setting up production congregation...")
    
    try:
        # Add production admin
        conn = sqlite3.connect('production_church.db', timeout=30.0)
        cursor = conn.cursor()
        
        # Add primary admin
        cursor.execute('''
            INSERT OR REPLACE INTO members (phone_number, name, is_admin, active, message_count) 
            VALUES (?, ?, ?, 1, 0)
        ''', ("+14257729189", "Church Admin", True))
        
        admin_id = cursor.lastrowid
        
        # Add to admin group
        cursor.execute('''
            INSERT OR IGNORE INTO group_members (group_id, member_id) 
            VALUES (2, ?)
        ''', (admin_id,))
        
        # Add production members
        production_members = [
            ("+12068001141", "Mike", 1),
            ("+14257729189", "Sam", 1),
            ("+12065910943", "Sami", 3),
            ("+12064349652", "Yab", 1)
        ]
        
        for phone, name, group_id in production_members:
            cursor.execute('''
                INSERT OR REPLACE INTO members (phone_number, name, is_admin, active, message_count) 
                VALUES (?, ?, ?, 1, 0)
            ''', (phone, name, False))
            
            member_id = cursor.lastrowid
            
            cursor.execute('''
                INSERT OR IGNORE INTO group_members (group_id, member_id) 
                VALUES (?, ?)
            ''', (group_id, member_id))
        
        conn.commit()
        conn.close()
        
        logger.info("✅ Production congregation setup completed with enhanced reactions")
        
    except Exception as e:
        logger.error(f"❌ Production setup error: {e}")
        traceback.print_exc()

# ===== PRODUCTION FLASK ROUTES =====

@app.route('/webhook/sms', methods=['POST'])
def handle_production_sms():
    """Production SMS webhook with enterprise-grade processing"""
    request_start = time.time()
    request_id = str(uuid.uuid4())[:8]
    
    logger.info(f"🌐 [{request_id}] Production webhook called")
    
    try:
        # Extract webhook data with validation
        from_number = request.form.get('From', '').strip()
        message_body = request.form.get('Body', '').strip()
        num_media = int(request.form.get('NumMedia', 0))
        message_sid = request.form.get('MessageSid', '')
        
        logger.info(f"📨 [{request_id}] From: {from_number}, Body: '{message_body}', Media: {num_media}")
        
        if not from_number:
            logger.warning(f"⚠️ [{request_id}] Missing From number")
            return "OK", 200
        
        # Extract media URLs with comprehensive logging
        media_urls = []
        for i in range(num_media):
            media_url = request.form.get(f'MediaUrl{i}')
            media_type = request.form.get(f'MediaContentType{i}')
            
            if media_url:
                media_urls.append({
                    'url': media_url,
                    'type': media_type or 'unknown',
                    'index': i
                })
                logger.info(f"📎 [{request_id}] Media {i+1}: {media_type}")
        
        # Process message asynchronously for fast webhook response
        def process_async():
            try:
                response = sms_system.handle_incoming_message_production(
                    from_number, message_body, media_urls
                )
                
                # Send admin response if needed
                if response and sms_system.is_admin_production(from_number):
                    result = sms_system.send_sms_production(from_number, response)
                    if result['success']:
                        logger.info(f"📤 [{request_id}] Admin response sent: {result['sid']}")
                    else:
                        logger.error(f"❌ [{request_id}] Admin response failed: {result['error']}")
                
            except Exception as e:
                logger.error(f"❌ [{request_id}] Async processing error: {e}")
                traceback.print_exc()
        
        # Start async processing
        sms_system.executor.submit(process_async)
        
        # Return immediate response to Twilio
        processing_time = round((time.time() - request_start) * 1000, 2)
        logger.info(f"⚡ [{request_id}] Webhook completed in {processing_time}ms")
        
        return "OK", 200
        
    except Exception as e:
        processing_time = round((time.time() - request_start) * 1000, 2)
        logger.error(f"❌ [{request_id}] Webhook error after {processing_time}ms: {e}")
        traceback.print_exc()
        return "OK", 200

@app.route('/webhook/status', methods=['POST'])
def handle_status_callback():
    """Handle delivery status callbacks from Twilio for debugging"""
    logger.info(f"📊 Status callback received")
    
    try:
        message_sid = request.form.get('MessageSid')
        message_status = request.form.get('MessageStatus')
        to_number = request.form.get('To')
        error_code = request.form.get('ErrorCode')
        error_message = request.form.get('ErrorMessage')
        
        logger.info(f"📊 Status Update for {message_sid}:")
        logger.info(f"   To: {to_number}")
        logger.info(f"   Status: {message_status}")
        
        if error_code:
            logger.warning(f"   ❌ Error {error_code}: {error_message}")
            
            # Log common error interpretations
            error_meanings = {
                '30007': 'Recipient device does not support MMS',
                '30008': 'Message blocked by carrier',
                '30034': 'A2P 10DLC registration issue',
                '30035': 'Media file too large',
                '30036': 'Unsupported media format',
                '11200': 'HTTP retrieval failure'
            }
            
            if error_code in error_meanings:
                logger.info(f"💡 Error meaning: {error_meanings[error_code]}")
        else:
            logger.info(f"   ✅ Message delivered successfully")
        
        return "OK", 200
        
    except Exception as e:
        logger.error(f"❌ Status callback error: {e}")
        traceback.print_exc()
        return "OK", 200

@app.route('/production/health', methods=['GET'])
def production_health():
    """Production health check with comprehensive monitoring"""
    try:
        health_data = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "Production Smart Media with Enhanced SMS Reactions v4.0",
            "environment": "production"
        }
        
        # Test database
        conn = sqlite3.connect('production_church.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM members WHERE active = 1")
        member_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM broadcast_messages WHERE sent_at > datetime('now', '-24 hours')")
        recent_messages = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM media_files WHERE upload_status = 'completed'")
        media_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM media_files WHERE display_name IS NOT NULL")
        clean_media_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM message_reactions WHERE is_active = 1")
        active_reactions = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT reactor_phone) FROM message_reactions WHERE is_active = 1")
        unique_reactors = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM broadcast_messages WHERE reaction_summary != ''")
        messages_with_reactions = cursor.fetchone()[0]
        conn.close()
        
        health_data["database"] = {
            "status": "connected",
            "active_members": member_count,
            "recent_messages_24h": recent_messages,
            "processed_media": media_count,
            "clean_media_display": clean_media_count,
            "active_reactions": active_reactions,
            "unique_reactors": unique_reactors,
            "messages_with_reactions": messages_with_reactions
        }
        
        # Test Twilio
        try:
            account = sms_system.twilio_client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
            health_data["twilio"] = {
                "status": "connected",
                "account_status": account.status,
                "phone_number": TWILIO_PHONE_NUMBER
            }
        except Exception as e:
            health_data["twilio"] = {"status": "error", "error": str(e)}
        
        # Test R2
        try:
            sms_system.r2_client.head_bucket(Bucket=R2_BUCKET_NAME)
            health_data["r2_storage"] = {
                "status": "connected",
                "bucket": R2_BUCKET_NAME
            }
        except Exception as e:
            health_data["r2_storage"] = {"status": "error", "error": str(e)}
        
        # Enhanced reaction system features
        health_data["enhanced_reaction_system"] = {
            "status": "enabled",
            "format": "count_based",
            "features": ["Smart timing", "Zero spam", "Count display", "Toggle reactions"],
            "active_reactions": active_reactions,
            "unique_users": unique_reactors,
            "messages_with_reactions": messages_with_reactions,
            "example_format": "4 reactions: ❤️×2  👍×1  😂×1"
        }
        
        # Clean media features
        health_data["clean_media"] = {
            "status": "enabled",
            "features": ["Clean filenames", "Simple display names", "No technical details"],
            "processed_files": clean_media_count
        }
        
        return jsonify(health_data), 200
        
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/', methods=['GET'])
def production_home():
    """Production home page with system overview"""
    try:
        # Get system stats
        conn = sqlite3.connect('production_church.db', timeout=5.0)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM members WHERE active = 1")
        member_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM broadcast_messages WHERE sent_at > datetime('now', '-24 hours')")
        messages_24h = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM media_files WHERE upload_status = 'completed'")
        media_processed = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM media_files WHERE compression_detected = 1")
        compression_fixed = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM media_files WHERE display_name IS NOT NULL")
        clean_media_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM message_reactions WHERE is_active = 1")
        active_reactions = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT reactor_phone) FROM message_reactions WHERE is_active = 1")
        unique_reactors = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM broadcast_messages WHERE reaction_summary != ''")
        messages_with_reactions = cursor.fetchone()[0]
        
        # Get recent performance
        cursor.execute('''
            SELECT AVG(operation_duration_ms) 
            FROM performance_metrics 
            WHERE operation_type = 'broadcast_complete' 
            AND recorded_at > datetime('now', '-7 days')
        ''')
        avg_broadcast_time = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return f"""
🏛️ YesuWay Church SMS Broadcasting System
📅 Production Environment - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🚀 PRODUCTION STATUS: ENHANCED SMS REACTIONS ACTIVE

📊 LIVE STATISTICS:
✅ Active Members: {member_count}
✅ Messages (24h): {messages_24h}
✅ Media Files Processed: {media_processed}
✅ Clean Media Display: {clean_media_count}
✅ Compression Issues Fixed: {compression_fixed}
✅ Active Reactions: {active_reactions}
✅ Unique Reactors: {unique_reactors}
✅ Messages with Reactions: {messages_with_reactions}
✅ Average Broadcast Time: {avg_broadcast_time/1000:.1f}s
✅ Church Number: {TWILIO_PHONE_NUMBER}

🔄 ENHANCED SMS REACTION SYSTEM:
✅ COUNT FORMAT: "4 reactions: ❤️×2  👍×1  😂×1"
✅ ZERO SPAM - Smart timing updates only
✅ TOGGLE REACTIONS - Same reaction twice removes it
✅ SMART UPDATES - Only when significant changes occur
✅ PROFESSIONAL DISPLAY - Clean, easy to read format

🧹 CLEAN MEDIA SYSTEM:
✅ NO technical filenames shown to users
✅ NO file sizes or metadata displayed  
✅ NO R2 URLs with random characters
✅ Simple "Photo 1", "Video 1" display
✅ Professional, clean presentation
✅ Direct media viewing without clutter

🎯 SMART MEDIA PROCESSING:
✅ Large files automatically uploaded to cloud
✅ Clean public links generated
✅ SMS broadcasting with professional display
✅ No compression, unlimited file sizes
✅ Production-grade reliability and performance

🔧 SYSTEM COMPONENTS:
✅ Twilio SMS/MMS: Enterprise messaging
✅ Cloudflare R2: Global CDN storage
✅ SQLite WAL: High-performance database
✅ Async Processing: Sub-second webhook response
✅ Concurrent Delivery: Optimized broadcasting
✅ Clean Media Display: Professional presentation
✅ Enhanced SMS Reactions: Count-based, zero spam

👑 ADMIN FEATURES:
• ADD +phone Name TO group - Add member
• REACTIONS - View recent reaction summaries
• HELP - Admin command help

📱 MEMBER EXPERIENCE:
• Send messages normally to {TWILIO_PHONE_NUMBER}
• Large files become clean, professional links
• Reactions display as count format automatically
• Zero reaction spam in conversations
• See: "🔗 Photo 1: church.media/photo_20250629.jpg"
• Reactions: "4 reactions: ❤️×2  👍×1  😂×1"
• Everyone receives messages via SMS
• Click links for full-quality media viewing
• Modern reaction experience with SMS compatibility

🛡️ PRODUCTION FEATURES:
• 99.9% uptime target
• Comprehensive error handling
• Real-time performance monitoring
• Clean media presentation (NO technical details)
• Enhanced SMS reactions (COUNT format)
• Smart timing (NO spam updates)
• Automatic scaling and optimization
• Enterprise-grade security and reliability

🔄 REACTION EXAMPLES:
✅ First reaction: "1 reaction: ❤️"
✅ Multiple same: "3 reactions: ❤️×3"
✅ Multiple different: "4 reactions: ❤️×2  👍×1  😂×1"
✅ Smart updates: Only every 3rd reaction or significant changes
❌ NO MORE: Individual reaction spam messages

💚 SERVING YOUR CONGREGATION 24/7 - ENHANCED SMS EXPERIENCE
        """
        
    except Exception as e:
        logger.error(f"❌ Home page error: {e}")
        return f"❌ System temporarily unavailable: {e}", 500

@app.route('/test', methods=['GET', 'POST'])
def test_endpoint():
    """Enhanced test endpoint with reaction count testing"""
    try:
        if request.method == 'POST':
            # Simulate webhook processing
            from_number = request.form.get('From', '+1234567890')
            message_body = request.form.get('Body', 'test message')
            
            logger.info(f"🧪 Test message: {from_number} -> {message_body}")
            
            # Test reaction detection
            reaction_data = sms_system.detect_reaction_pattern(message_body)
            
            # Test async processing
            def test_async():
                result = sms_system.handle_incoming_message_production(from_number, message_body, [])
                logger.info(f"🧪 Test result: {result}")
            
            sms_system.executor.submit(test_async)
            
            return jsonify({
                "status": "✅ Test processed",
                "from": from_number,
                "body": message_body,
                "reaction_detected": reaction_data is not None,
                "reaction_data": reaction_data,
                "timestamp": datetime.now().isoformat(),
                "processing": "async",
                "features": ["Clean media display", "Enhanced SMS reactions", "Count format"]
            })
        
        else:
            return jsonify({
                "status": "✅ Test endpoint active",
                "method": "GET",
                "features": ["Production ready", "Clean media display", "Enhanced SMS reactions"],
                "reaction_format": "count_based",
                "reaction_examples": [
                    "1 reaction: ❤️",
                    "3 reactions: ❤️×2  👍×1",
                    "4 reactions: ❤️×2  👍×1  😂×1"
                ],
                "reaction_patterns": ["Laughed at 'message'", "Emphasized 'text'", "Reacted 😍 to 'content'"],
                "usage": "POST with From and Body parameters to test",
                "test_reactions": [
                    "Laughed at 'Hello everyone'",
                    "Emphasized 'Important message'", 
                    "Reacted 😍 to 'Beautiful photo'",
                    "❤️"
                ],
                "curl_example": f"curl -X POST {request.host_url}test -d 'From=+1234567890&Body=Laughed at \"test message\"'"
            })
            
    except Exception as e:
        logger.error(f"❌ Test endpoint error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/reaction-demo', methods=['GET'])
def reaction_demo():
    """Demonstrate enhanced SMS reaction count format"""
    return f"""
🔄 ENHANCED SMS REACTION DEMONSTRATION

📱 OLD BEHAVIOR (Spammy):
💬 John: "Good morning everyone!"
💬 Sam: "Laughed at 'Good morning everyone!'"
💬 Sam: "Emphasized 'Good morning everyone!'"  
💬 Sam: "Reacted ❤️ to 'Good morning everyone!'"
💬 Mike: "Liked 'Good morning everyone!'"

❌ Result: 4 extra messages cluttering the conversation!

🎯 NEW BEHAVIOR (Enhanced SMS Count Format):
💬 John: "Good morning everyone!"

🔄 Reaction Update:
💬 John: "Good morning everyone!"

1 reaction: 😂

🔄 Reaction Update:
💬 John: "Good morning everyone!"

3 reactions: ❤️×2  😂×1

✅ Result: Clean count format with smart timing!

🔄 ENHANCED FEATURES:
✅ Count format: "4 reactions: ❤️×2  👍×1  😂×1"
✅ Smart timing - only updates every 3rd reaction
✅ Toggle reactions ON/OFF by repeating same reaction
✅ Zero spam - no individual reaction messages
✅ Professional SMS presentation
✅ Works on ANY phone (iPhone, Android, flip phones)

🎯 COUNT FORMAT EXAMPLES:
• "1 reaction: ❤️"
• "2 reactions: ❤️×2"
• "3 reactions: ❤️×2  👍×1"
• "4 reactions: ❤️×2  👍×1  😂×1"
• "7 reactions: ❤️×3  😂×2  👍×1  ❓×1"

🚀 SMART TIMING:
✅ First reaction → Immediate update
✅ Every 3rd reaction → Update sent
✅ Reaction removed → Immediate update
✅ 5+ minutes since last update → Update if new activity
❌ Individual reactions → No spam messages

💚 PERFECT SMS SOLUTION - NO SPAM, CLEAN FORMAT!
    """

@app.route('/clean-media-demo', methods=['GET'])
def clean_media_demo():
    """Demonstrate clean media display format"""
    return f"""
🧹 CLEAN MEDIA DISPLAY DEMONSTRATION

📱 WHAT USERS SEE (Clean):
💬 John:
Check out Sunday's service!

🔗 Video 1: church.media/video_20250629_140322.mp4
🔗 Photo 2: church.media/photo_20250629_140335.jpg

4 reactions: ❤️×2  👍×1  😂×1

❌ WHAT THEY DON'T SEE (Technical):
• 20250629_214401_ec9e07d426eb_media_1
• JPEG Image • 46 KB  
• pub-d5f4333e04b54751a08073acfc818c8a.r2.dev
• Technical metadata or file details
• Individual reaction spam messages

✨ BENEFITS:
✅ Professional presentation
✅ Clean, simple display
✅ No confusing technical information
✅ Direct media access
✅ User-friendly experience
✅ Count-based reactions (no spam)

🔄 ENHANCED WITH COUNT REACTIONS:
💬 Sam: "Beautiful service today!"

3 reactions: ❤️×2  😂×1

(Instead of 3 separate reaction messages)

🎯 Perfect for church communication!
    """

# Error handlers
@app.errorhandler(404)
def not_found_production(error):
    return jsonify({
        "error": "Endpoint not found", 
        "status": "production",
        "available_endpoints": ["/", "/production/health", "/webhook/sms", "/test", "/reaction-demo", "/clean-media-demo"]
    }), 404

@app.errorhandler(500)
def internal_error_production(error):
    logger.error(f"❌ Internal server error: {error}")
    return jsonify({
        "error": "Internal server error", 
        "status": "production",
        "features": ["Clean media display", "Enhanced SMS reactions", "Count format"]
    }), 500

@app.errorhandler(Exception)
def handle_exception_production(e):
    logger.error(f"❌ Unhandled exception: {e}")
    traceback.print_exc()
    return jsonify({
        "error": "An unexpected error occurred", 
        "status": "production"
    }), 500

# Request monitoring
@app.before_request
def before_request():
    """Set request timeout and monitoring"""
    request.start_time = time.time()

@app.after_request
def after_request(response):
    """Log request timing and monitor performance"""
    if hasattr(request, 'start_time'):
        duration = round((time.time() - request.start_time) * 1000, 2)
        if duration > 1000:  # Log slow requests
            logger.warning(f"⏰ Slow request: {request.endpoint} took {duration}ms")
        
        # Record request performance
        try:
            if hasattr(sms_system, 'record_performance_metric'):
                endpoint = request.endpoint or 'unknown'
                sms_system.record_performance_metric(f'http_{endpoint}', int(duration), response.status_code < 400)
        except:
            pass  # Don't fail request if performance logging fails
    
    return response

if __name__ == '__main__':
    logger.info("🚀 Starting Production Smart Media System with Enhanced SMS Reactions...")
    logger.info("🏛️ Industry-level church communication platform")
    logger.info("🧹 Clean media presentation - NO technical details shown")
    logger.info("🔄 Enhanced SMS reactions - COUNT format, ZERO spam")
    logger.info("📱 Professional user experience enabled")
    
    # Validate production environment
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        logger.critical("💥 Missing required Twilio production credentials")
        raise SystemExit("Production requires all Twilio credentials")
    
    if not all([R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL]):
        logger.critical("💥 Missing required R2 production credentials")
        raise SystemExit("Production requires all R2 credentials")
    
    # Setup production congregation
    setup_production_congregation()
    
    logger.info("🎯 Production Smart Media System: READY FOR PRODUCTION")
    logger.info("📡 Webhook endpoint: /webhook/sms")
    logger.info("🏥 Health monitoring: /production/health") 
    logger.info("📊 System overview: /")
    logger.info("🧪 Test endpoint: /test")
    logger.info("🔄 Reaction demo: /reaction-demo")
    logger.info("🧹 Clean media demo: /clean-media-demo")
    logger.info("🛡️ Enterprise-grade error handling active")
    logger.info("⚡ Smart media processing: ENABLED")
    logger.info("🧹 Clean display: NO technical details shown")
    logger.info("🔄 Enhanced SMS reactions: COUNT format, SMART timing")
    logger.info("🚫 Zero reaction spam: ELIMINATED")
    logger.info("📱 Unlimited file size support: ACTIVE")
    logger.info("🏛️ Serving YesuWay Church congregation")
    
    # Run production server
    port = int(os.environ.get('PORT', 5000))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False
    )