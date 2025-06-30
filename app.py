import os
from sched import scheduler
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
#import schedule

# Production logging configuration - Windows compatible
import sys
import io

# Set UTF-8 encoding for Windows console
if sys.platform.startswith('win'):
    # Force UTF-8 output for Windows
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('production_sms.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Production Configuration - All from environment variables
# For development/testing, you can set these directly here:
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID') or 'your_twilio_account_sid_here'
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN') or 'your_twilio_auth_token_here'
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER') or 'your_twilio_phone_number_here'

# Cloudflare R2 Configuration
R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID') or 'your_r2_access_key_here'
R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY') or 'your_r2_secret_key_here'
R2_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL') or 'your_r2_endpoint_here'
R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME', 'church-media-production')
R2_PUBLIC_URL = os.environ.get('R2_PUBLIC_URL') or 'your_r2_public_url_here'

# Development mode check
DEVELOPMENT_MODE = os.environ.get('DEVELOPMENT_MODE', 'True').lower() == 'true'

# Production Flask app
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max request

class ProductionChurchSMS:
    def __init__(self):
        """Initialize production-grade church SMS broadcasting system with smart reaction tracking"""
        self.twilio_client = None
        self.r2_client = None
        self.executor = ThreadPoolExecutor(max_workers=10)
        self.conversation_pause_timer = None
        self.last_regular_message_time = None
        
        # Initialize Twilio client
        if DEVELOPMENT_MODE and (not TWILIO_ACCOUNT_SID or TWILIO_ACCOUNT_SID == 'your_twilio_account_sid_here'):
            logger.warning("DEVELOPMENT MODE: Twilio client disabled - using mock responses")
            self.twilio_client = None
        elif TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_ACCOUNT_SID != 'your_twilio_account_sid_here':
            try:
                self.twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                account = self.twilio_client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
                logger.info(f"SUCCESS: Twilio production connection established: {account.friendly_name}")
            except Exception as e:
                logger.error(f"ERROR: Twilio connection failed: {e}")
                if not DEVELOPMENT_MODE:
                    raise
        else:
            if DEVELOPMENT_MODE:
                logger.info("DEVELOPMENT MODE: Missing Twilio credentials - continuing with mocks")
                self.twilio_client = None
            else:
                logger.error("ERROR: Missing Twilio credentials")
                raise ValueError("Twilio credentials required for production")
        
        # Initialize Cloudflare R2 client
        if DEVELOPMENT_MODE and (not R2_ACCESS_KEY_ID or R2_ACCESS_KEY_ID == 'your_r2_access_key_here'):
            logger.warning("DEVELOPMENT MODE: R2 client disabled - using local storage")
            self.r2_client = None
        elif R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_ENDPOINT_URL and R2_ACCESS_KEY_ID != 'your_r2_access_key_here':
            try:
                self.r2_client = boto3.client(
                    's3',
                    endpoint_url=R2_ENDPOINT_URL,
                    aws_access_key_id=R2_ACCESS_KEY_ID,
                    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                    region_name='auto'
                )
                self.r2_client.head_bucket(Bucket=R2_BUCKET_NAME)
                logger.info(f"SUCCESS: Cloudflare R2 production connection established: {R2_BUCKET_NAME}")
            except Exception as e:
                logger.error(f"ERROR: R2 connection failed: {e}")
                if not DEVELOPMENT_MODE:
                    raise
        else:
            if DEVELOPMENT_MODE:
                logger.info("DEVELOPMENT MODE: Missing R2 credentials - continuing with local storage")
                self.r2_client = None
            else:
                logger.error("ERROR: Missing R2 credentials")
                raise ValueError("R2 credentials required for production")
        
        self.init_production_database()
        self.start_reaction_scheduler()
        logger.info("SUCCESS: Production Church SMS System with Smart Reaction Tracking initialized")
    
    def init_production_database(self):
        """Initialize production database with smart reaction tracking"""
        try:
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.execute('PRAGMA synchronous=NORMAL;')
            conn.execute('PRAGMA cache_size=10000;')
            conn.execute('PRAGMA temp_store=memory;')
            conn.execute('PRAGMA foreign_keys=ON;')
            
            cursor = conn.cursor()
            
            # Groups table
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
            
            # Members table
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
            
            # Group membership table
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
            
            # Messages table
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
                    is_reaction BOOLEAN DEFAULT FALSE,
                    target_message_id INTEGER,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (target_message_id) REFERENCES broadcast_messages (id)
                )
            ''')
            
            # Smart reaction tracking table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS message_reactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_message_id INTEGER NOT NULL,
                    reactor_phone TEXT NOT NULL,
                    reactor_name TEXT NOT NULL,
                    reaction_emoji TEXT NOT NULL,
                    reaction_text TEXT NOT NULL,
                    is_processed BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (target_message_id) REFERENCES broadcast_messages (id) ON DELETE CASCADE
                )
            ''')
            
            # Reaction summary tracking
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reaction_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary_type TEXT NOT NULL,
                    summary_content TEXT NOT NULL,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    messages_included INTEGER DEFAULT 0
                )
            ''')
            
            # Media files table
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
            
            # Delivery tracking table
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
            
            # Analytics table
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
            
            # Create indexes for performance including reaction tracking
            indexes = [
                'CREATE INDEX IF NOT EXISTS idx_members_phone ON members(phone_number)',
                'CREATE INDEX IF NOT EXISTS idx_members_active ON members(active)',
                'CREATE INDEX IF NOT EXISTS idx_messages_sent_at ON broadcast_messages(sent_at)',
                'CREATE INDEX IF NOT EXISTS idx_messages_is_reaction ON broadcast_messages(is_reaction)',
                'CREATE INDEX IF NOT EXISTS idx_messages_target ON broadcast_messages(target_message_id)',
                'CREATE INDEX IF NOT EXISTS idx_reactions_target ON message_reactions(target_message_id)',
                'CREATE INDEX IF NOT EXISTS idx_reactions_processed ON message_reactions(is_processed)',
                'CREATE INDEX IF NOT EXISTS idx_reactions_created ON message_reactions(created_at)',
                'CREATE INDEX IF NOT EXISTS idx_media_message_id ON media_files(message_id)',
                'CREATE INDEX IF NOT EXISTS idx_media_status ON media_files(upload_status)',
                'CREATE INDEX IF NOT EXISTS idx_delivery_message_id ON delivery_log(message_id)',
                'CREATE INDEX IF NOT EXISTS idx_delivery_status ON delivery_log(delivery_status)',
                'CREATE INDEX IF NOT EXISTS idx_analytics_metric ON system_analytics(metric_name, recorded_at)',
                'CREATE INDEX IF NOT EXISTS idx_performance_type ON performance_metrics(operation_type, recorded_at)'
            ]
            
            for index_sql in indexes:
                cursor.execute(index_sql)
            
            # Initialize groups if empty
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
            logger.info("✅ Production database with smart reaction tracking initialized")
            
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            traceback.print_exc()
            raise

    def detect_reaction_pattern(self, message_body):
        """Detect if message is a reaction using industry-standard patterns"""
        if not message_body:
            return None
        
        message_body = message_body.strip()
        
        # Industry-standard reaction patterns
        reaction_patterns = [
            # Apple iPhone reactions
            r'^(Loved|Liked|Disliked|Laughed at|Emphasized|Questioned)\s*["\'""](.+)["\'""]',
            # Android reactions  
            r'^(Reacted\s*([😀-🿿]+)\s*to)\s*["\'""](.+)["\'""]',
            # Single emoji reactions
            r"^([😀-🿿]+)\s*$",
            # Generic reaction patterns
            r'^([😀-🿿]+)\s*to\s*["\'""](.+)["\'""]',
            # Text-based reactions
            r'^(👍|👎|❤️|😂|😢|😮|😡)\s*$'
        ]
        
        for pattern in reaction_patterns:
            match = re.match(pattern, message_body, re.UNICODE)
            if match:
                groups = match.groups()
                
                if len(groups) >= 2:
                    reaction_type = groups[0]
                    target_message = groups[-1] if len(groups) > 1 else ""
                else:
                    reaction_type = groups[0]
                    target_message = ""
                
                # Map reaction types to emojis for consistent tracking
                reaction_mapping = {
                    'Loved': '❤️',
                    'Liked': '👍',
                    'Disliked': '👎',
                    'Laughed at': '😂',
                    'Emphasized': '‼️',
                    'Questioned': '❓'
                }
                
                emoji = reaction_mapping.get(reaction_type, reaction_type)
                
                # Extract emoji if reaction_type contains emoji
                emoji_match = re.search(r'([😀-🿿]+)', emoji)
                if emoji_match:
                    emoji = emoji_match.group(1)
                
                logger.info(f"🎯 Industry reaction detected: '{emoji}' to message fragment: '{target_message[:50]}...'")
                
                return {
                    'emoji': emoji,
                    'target_message_fragment': target_message[:100],
                    'reaction_type': reaction_type,
                    'full_pattern': message_body
                }
        
        return None

    def find_target_message_for_reaction(self, target_fragment, reactor_phone, hours_back=24):
        """Find the target message for a reaction using smart matching"""
        try:
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            # Look for recent non-reaction messages
            since_time = datetime.now() - timedelta(hours=hours_back)
            
            cursor.execute('''
                SELECT id, original_message, from_phone, from_name, sent_at
                FROM broadcast_messages 
                WHERE sent_at > ? 
                AND from_phone != ?
                AND is_reaction = 0
                ORDER BY sent_at DESC
                LIMIT 10
            ''', (since_time.isoformat(), reactor_phone))
            
            recent_messages = cursor.fetchall()
            conn.close()
            
            if not recent_messages:
                logger.info(f"🔍 No recent messages found for reaction matching")
                return None
            
            # Smart matching algorithm
            best_match = None
            best_score = 0
            
            if target_fragment:
                target_words = set(target_fragment.lower().split())
                
                for msg_id, original_msg, from_phone, from_name, sent_at in recent_messages:
                    if not original_msg:
                        continue
                    
                    message_words = set(original_msg.lower().split())
                    
                    # Calculate similarity score
                    if target_words and message_words:
                        common_words = target_words.intersection(message_words)
                        score = len(common_words) / max(len(target_words), len(message_words))
                        
                        # Boost score for exact substring matches
                        if target_fragment.lower() in original_msg.lower():
                            score += 0.5
                        
                        if score > best_score and score > 0.3:
                            best_score = score
                            best_match = {
                                'id': msg_id,
                                'message': original_msg,
                                'from_phone': from_phone,
                                'from_name': from_name,
                                'sent_at': sent_at,
                                'similarity_score': score
                            }
            
            # Fallback to most recent message if no good match
            if not best_match and recent_messages:
                msg_id, original_msg, from_phone, from_name, sent_at = recent_messages[0]
                best_match = {
                    'id': msg_id,
                    'message': original_msg,
                    'from_phone': from_phone,
                    'from_name': from_name,
                    'sent_at': sent_at,
                    'similarity_score': 0.0
                }
                logger.info(f"🎯 Using most recent message as fallback: Message {msg_id}")
            
            if best_match:
                logger.info(f"✅ Found reaction target (score: {best_match['similarity_score']:.2f}): "
                           f"Message {best_match['id']} from {best_match['from_name']}")
                
            return best_match
        
        except Exception as e:
            logger.error(f"❌ Error finding reaction target: {e}")
            traceback.print_exc()
            return None

    def store_reaction_silently(self, reactor_phone, reaction_data, target_message):
        """Store reaction silently without broadcasting - industry approach"""
        try:
            reactor = self.get_member_info(reactor_phone)
            if not reactor:
                logger.warning(f"❌ Reaction from unregistered number: {reactor_phone}")
                return False
            
            target_msg_id = target_message['id']
            reaction_emoji = reaction_data['emoji']
            reaction_text = reaction_data['full_pattern']
            
            logger.info(f"🔇 Storing silent reaction: {reactor['name']} reacted '{reaction_emoji}' to message {target_msg_id}")
            
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            # Store reaction silently
            cursor.execute('''
                INSERT INTO message_reactions 
                (target_message_id, reactor_phone, reactor_name, reaction_emoji, reaction_text, is_processed) 
                VALUES (?, ?, ?, ?, ?, 0)
            ''', (target_msg_id, reactor_phone, reactor['name'], reaction_emoji, reaction_text))
            
            # Mark original message to track it has reactions
            cursor.execute('''
                UPDATE broadcast_messages 
                SET message_type = 'text_with_reactions'
                WHERE id = ?
            ''', (target_msg_id,))
            
            conn.commit()
            conn.close()
            
            logger.info(f"✅ Reaction stored silently - no broadcast sent")
            return True
        
        except Exception as e:
            logger.error(f"❌ Error storing silent reaction: {e}")
            traceback.print_exc()
            return False

    def start_reaction_scheduler(self):
        """Start the smart reaction summary scheduler"""
        def run_scheduler():
            # Schedule daily summary at 8 PM
            scheduler.every().day.at("20:00").do(self.send_daily_reaction_summary)
            
            while True:
                scheduler.run_pending()
                time.sleep(60)  # Check every minute
        
        # Start scheduler in background thread
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        logger.info("✅ Smart reaction scheduler started - Daily summaries at 8 PM")

    def reset_conversation_pause_timer(self):
        """Reset the 30-minute conversation pause timer"""
        if self.conversation_pause_timer:
            self.conversation_pause_timer.cancel()
        
        # Set timer for 30 minutes from now
        self.conversation_pause_timer = threading.Timer(1800.0, self.send_pause_reaction_summary)  # 30 minutes
        self.conversation_pause_timer.start()
        self.last_regular_message_time = datetime.now()
        logger.debug("🕐 Conversation pause timer reset - 30 minutes")

    def send_pause_reaction_summary(self):
        """Send reaction summary after 30 minutes of conversation pause"""
        try:
            # Get unprocessed reactions from the last 2 hours
            since_time = datetime.now() - timedelta(hours=2)
            
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT mr.target_message_id, bm.from_name, bm.original_message, 
                       mr.reaction_emoji, COUNT(*) as reaction_count
                FROM message_reactions mr
                JOIN broadcast_messages bm ON mr.target_message_id = bm.id
                WHERE mr.is_processed = 0 
                AND mr.created_at > ?
                GROUP BY mr.target_message_id, mr.reaction_emoji
                ORDER BY bm.sent_at DESC
            ''', (since_time.isoformat(),))
            
            reaction_data = cursor.fetchall()
            
            if not reaction_data:
                conn.close()
                logger.info("🔇 No unprocessed reactions for pause summary")
                return
            
            # Build smart summary
            summary_lines = ["📊 Recent reactions:"]
            messages_included = 0
            
            # Group by message
            message_reactions = {}
            for target_id, from_name, original_msg, emoji, count in reaction_data:
                if target_id not in message_reactions:
                    message_reactions[target_id] = {
                        'from_name': from_name,
                        'message': original_msg,
                        'reactions': {}
                    }
                message_reactions[target_id]['reactions'][emoji] = count
            
            for target_id, msg_data in message_reactions.items():
                messages_included += 1
                message_preview = msg_data['message'][:40] + "..." if len(msg_data['message']) > 40 else msg_data['message']
                
                # Format reaction counts
                reaction_parts = []
                for emoji, count in msg_data['reactions'].items():
                    if count == 1:
                        reaction_parts.append(emoji)
                    else:
                        reaction_parts.append(f"{emoji}×{count}")
                
                reaction_display = " ".join(reaction_parts)
                summary_lines.append(f"💬 {msg_data['from_name']}: \"{message_preview}\" → {reaction_display}")
            
            # Mark all reactions as processed
            cursor.execute('''
                UPDATE message_reactions 
                SET is_processed = 1 
                WHERE is_processed = 0 
                AND created_at > ?
            ''', (since_time.isoformat(),))
            
            # Store summary record
            summary_content = "\n".join(summary_lines)
            cursor.execute('''
                INSERT INTO reaction_summaries (summary_type, summary_content, messages_included) 
                VALUES ('pause_summary', ?, ?)
            ''', (summary_content, messages_included))
            
            conn.commit()
            conn.close()
            
            # Broadcast summary to congregation
            self.broadcast_summary_to_congregation(summary_content)
            
            logger.info(f"✅ Pause reaction summary sent - {messages_included} messages included")
        
        except Exception as e:
            logger.error(f"❌ Error sending pause reaction summary: {e}")
            traceback.print_exc()

    def send_daily_reaction_summary(self):
        """Send daily reaction summary at 8 PM"""
        try:
            # Get reactions from today that haven't been processed
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT mr.target_message_id, bm.from_name, bm.original_message, 
                       mr.reaction_emoji, COUNT(*) as reaction_count
                FROM message_reactions mr
                JOIN broadcast_messages bm ON mr.target_message_id = bm.id
                WHERE mr.is_processed = 0 
                AND mr.created_at >= ?
                GROUP BY mr.target_message_id, mr.reaction_emoji
                ORDER BY reaction_count DESC, bm.sent_at DESC
                LIMIT 10
            ''', (today_start.isoformat(),))
            
            reaction_data = cursor.fetchall()
            
            if not reaction_data:
                conn.close()
                logger.info("🔇 No reactions for daily summary")
                return
            
            # Build comprehensive daily summary
            summary_lines = ["📊 TODAY'S REACTIONS:"]
            messages_included = 0
            total_reactions = 0
            
            # Group by message
            message_reactions = {}
            for target_id, from_name, original_msg, emoji, count in reaction_data:
                total_reactions += count
                if target_id not in message_reactions:
                    message_reactions[target_id] = {
                        'from_name': from_name,
                        'message': original_msg,
                        'reactions': {},
                        'total_count': 0
                    }
                message_reactions[target_id]['reactions'][emoji] = count
                message_reactions[target_id]['total_count'] += count
            
            # Sort by total reaction count
            sorted_messages = sorted(message_reactions.items(), 
                                   key=lambda x: x[1]['total_count'], reverse=True)
            
            for target_id, msg_data in sorted_messages[:5]:  # Top 5 most reacted messages
                messages_included += 1
                message_preview = msg_data['message'][:50] + "..." if len(msg_data['message']) > 50 else msg_data['message']
                
                # Format reaction counts
                reaction_parts = []
                for emoji, count in msg_data['reactions'].items():
                    if count == 1:
                        reaction_parts.append(emoji)
                    else:
                        reaction_parts.append(f"{emoji}×{count}")
                
                reaction_display = " ".join(reaction_parts)
                total_for_msg = msg_data['total_count']
                summary_lines.append(f"• {msg_data['from_name']}: \"{message_preview}\" ({total_for_msg} reactions: {reaction_display})")
            
            # Add engagement stats
            cursor.execute('''
                SELECT COUNT(DISTINCT reactor_phone) 
                FROM message_reactions 
                WHERE is_processed = 0 
                AND created_at >= ?
            ''', (today_start.isoformat(),))
            
            unique_reactors = cursor.fetchone()[0]
            summary_lines.append(f"\n🎯 Today's engagement: {total_reactions} reactions from {unique_reactors} members")
            
            # Mark all today's reactions as processed
            cursor.execute('''
                UPDATE message_reactions 
                SET is_processed = 1 
                WHERE is_processed = 0 
                AND created_at >= ?
            ''', (today_start.isoformat(),))
            
            # Store summary record
            summary_content = "\n".join(summary_lines)
            cursor.execute('''
                INSERT INTO reaction_summaries (summary_type, summary_content, messages_included) 
                VALUES ('daily_summary', ?, ?)
            ''', (summary_content, messages_included))
            
            conn.commit()
            conn.close()
            
            # Broadcast summary to congregation
            self.broadcast_summary_to_congregation(summary_content)
            
            logger.info(f"✅ Daily reaction summary sent - {messages_included} messages, {total_reactions} reactions")
        
        except Exception as e:
            logger.error(f"❌ Error sending daily reaction summary: {e}")
            traceback.print_exc()

    def broadcast_summary_to_congregation(self, summary_content):
        """Broadcast reaction summary to entire congregation"""
        try:
            # Get all active members
            recipients = self.get_all_active_members()
            
            if not recipients:
                logger.warning("❌ No active recipients for summary broadcast")
                return
            
            logger.info(f"📤 Broadcasting reaction summary to {len(recipients)} members")
            
            # Concurrent delivery of summary
            def send_summary_to_member(member):
                result = self.send_sms(member['phone'], summary_content)
                if result['success']:
                    logger.info(f"✅ Summary delivered to {member['name']}")
                else:
                    logger.error(f"❌ Summary failed to {member['name']}: {result['error']}")
            
            # Execute concurrent delivery
            futures = []
            for recipient in recipients:
                future = self.executor.submit(send_summary_to_member, recipient)
                futures.append(future)
            
            # Wait for all deliveries
            for future in futures:
                try:
                    future.result(timeout=30)
                except Exception as e:
                    logger.error(f"❌ Summary delivery error: {e}")
            
            logger.info(f"✅ Reaction summary broadcast completed")
        
        except Exception as e:
            logger.error(f"❌ Error broadcasting summary: {e}")
            traceback.print_exc()

    def clean_phone_number(self, phone):
        """Clean and standardize phone numbers"""
        if not phone:
            return None
        
        digits = re.sub(r'\D', '', str(phone))
        
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
    
    def download_media_from_twilio(self, media_url):
        """Download media from Twilio with authentication"""
        start_time = time.time()
        try:
            logger.info(f"📥 Downloading media: {media_url}")
            
            response = requests.get(
                media_url,
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                timeout=60,
                stream=True
            )
            
            if response.status_code == 200:
                content = b''
                content_length = 0
                
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
    
    def generate_clean_filename(self, mime_type, media_index=1):
        """Generate clean, user-friendly filename"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
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
        
        if media_index > 1:
            base_name += f"_{media_index}"
        
        clean_filename = f"church/{base_name}{extension}"
        
        return clean_filename, display_name
    
    def upload_to_r2(self, file_content, object_key, mime_type, metadata=None):
        """Upload file to Cloudflare R2"""
        start_time = time.time()
        try:
            logger.info(f"☁️ Uploading to R2: {object_key}")
            
            upload_metadata = {
                'church-system': 'yesuway-production',
                'upload-timestamp': datetime.now().isoformat(),
                'content-hash': hashlib.sha256(file_content).hexdigest()
            }
            
            if metadata:
                upload_metadata.update(metadata)
            
            self.r2_client.put_object(
                Bucket=R2_BUCKET_NAME,
                Key=object_key,
                Body=file_content,
                ContentType=mime_type,
                ContentDisposition='inline',
                CacheControl='public, max-age=31536000',
                Metadata=upload_metadata,
                ServerSideEncryption='AES256'
            )
            
            if R2_PUBLIC_URL:
                public_url = f"{R2_PUBLIC_URL.rstrip('/')}/{object_key}"
            else:
                public_url = self.r2_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': R2_BUCKET_NAME, 'Key': object_key},
                    ExpiresIn=31536000
                )
            
            duration_ms = int((time.time() - start_time) * 1000)
            self.record_performance_metric('r2_upload', duration_ms, True)
            
            logger.info(f"✅ Upload successful: {public_url}")
            return public_url
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.record_performance_metric('r2_upload', duration_ms, False, str(e))
            logger.error(f"❌ R2 upload failed: {e}")
            traceback.print_exc()
            return None
    
    def process_media_files(self, message_id, media_urls):
        """Process media files with clean display names"""
        logger.info(f"🔄 Processing {len(media_urls)} media files for message {message_id}")
        
        processed_links = []
        processing_errors = []
        
        for i, media in enumerate(media_urls):
            media_url = media.get('url', '')
            media_type = media.get('type', 'unknown')
            
            try:
                logger.info(f"📎 Processing media {i+1}/{len(media_urls)}: {media_type}")
                
                media_data = self.download_media_from_twilio(media_url)
                
                if not media_data:
                    error_msg = f"Failed to download media {i+1}"
                    processing_errors.append(error_msg)
                    logger.error(error_msg)
                    continue
                
                file_size = media_data['size']
                compression_detected = file_size >= 4.8 * 1024 * 1024
                
                clean_filename, display_name = self.generate_clean_filename(
                    media_data['mime_type'], 
                    i+1
                )
                
                public_url = self.upload_to_r2(
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
        
        logger.info(f"✅ Media processing complete: {len(processed_links)} successful, {len(processing_errors)} errors")
        return processed_links, processing_errors
    
    def get_all_active_members(self, exclude_phone=None):
        """Get all active registered members"""
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
    
    def get_member_info(self, phone_number):
        """Get member info - registered members only, no auto-registration"""
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
            conn.close()
            
            if result:
                member_id, name, is_admin, msg_count = result
                return {
                    "id": member_id,
                    "name": name,
                    "is_admin": bool(is_admin),
                    "message_count": msg_count
                }
            else:
                logger.warning(f"❌ Unregistered number attempted access: {phone_number}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting member info: {e}")
            traceback.print_exc()
            return None
    
    def send_sms(self, to_phone, message_text, max_retries=3):
        """Send SMS with retry logic"""
        if DEVELOPMENT_MODE and not self.twilio_client:
            logger.info(f"DEVELOPMENT MODE: Mock SMS to {to_phone}: {message_text[:50]}...")
            return {
                "success": True,
                "sid": f"mock_sid_{uuid.uuid4().hex[:8]}",
                "attempt": 1
            }
        
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
                
                logger.info(f"SUCCESS: SMS sent to {to_phone}: {message_obj.sid}")
                return {
                    "success": True,
                    "sid": message_obj.sid,
                    "attempt": attempt + 1
                }
                
            except Exception as e:
                logger.warning(f"WARNING: SMS attempt {attempt + 1} failed for {to_phone}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))
                else:
                    duration_ms = int((time.time() - start_time) * 1000)
                    self.record_performance_metric('sms_send', duration_ms, False, str(e))
                    logger.error(f"ERROR: All SMS attempts failed for {to_phone}")
                    return {
                        "success": False,
                        "error": str(e),
                        "attempts": max_retries
                    }
    
    def format_message_with_media(self, original_message, sender, media_links=None):
        """Format message with clean media links"""
        if media_links:
            if len(media_links) == 1:
                media_item = media_links[0]
                formatted_message = f"💬 {sender['name']}:\n{original_message}\n\n🔗 {media_item['display_name']}: {media_item['url']}"
            else:
                media_text = "\n".join([f"🔗 {item['display_name']}: {item['url']}" for item in media_links])
                formatted_message = f"💬 {sender['name']}:\n{original_message}\n\n{media_text}"
        else:
            formatted_message = f"💬 {sender['name']}:\n{original_message}"
        
        return formatted_message
    
    def broadcast_message(self, from_phone, message_text, media_urls=None):
        """Broadcast message to all registered members with smart reaction tracking"""
        start_time = time.time()
        logger.info(f"📡 Starting broadcast from {from_phone}")
        
        try:
            sender = self.get_member_info(from_phone)
            
            if not sender:
                logger.warning(f"❌ Broadcast rejected - unregistered number: {from_phone}")
                return "You are not registered. Please contact church admin to be added to the system."
            
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
                 has_media, media_count, processing_status, delivery_status, is_reaction) 
                VALUES (?, ?, ?, ?, ?, ?, ?, 'processing', 'pending', 0)
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
                clean_media_links, processing_errors = self.process_media_files(message_id, media_urls)
                large_media_count = len(clean_media_links)
                
                if processing_errors:
                    logger.warning(f"⚠️ Media processing errors: {processing_errors}")
            
            # Format final message
            final_message = self.format_message_with_media(
                message_text, sender, clean_media_links
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
            
            # Reset conversation pause timer for regular messages
            self.reset_conversation_pause_timer()
            
            # Broadcast with concurrent delivery
            delivery_stats = {
                'sent': 0,
                'failed': 0,
                'total_time': 0,
                'errors': []
            }
            
            def send_to_member(member):
                member_start = time.time()
                result = self.send_sms(member['phone'], final_message)
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
            
            # Wait for all deliveries
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
            
            logger.info(f"📊 Broadcast completed in {total_time:.2f}s: "
                       f"{delivery_stats['sent']} sent, {delivery_stats['failed']} failed")
            
            # Return confirmation to sender if admin
            if sender['is_admin']:
                confirmation = f"✅ Broadcast completed in {total_time:.1f}s\n"
                confirmation += f"📊 Delivered: {delivery_stats['sent']}/{len(recipients)}\n"
                
                if large_media_count > 0:
                    confirmation += f"📎 Clean media links: {large_media_count}\n"
                
                if delivery_stats['failed'] > 0:
                    confirmation += f"⚠️ Failed deliveries: {delivery_stats['failed']}\n"
                
                confirmation += f"🔇 Smart reaction tracking: Active"
                return confirmation
            else:
                return None  # No confirmation for regular members
                
        except Exception as e:
            logger.error(f"❌ Broadcast error: {e}")
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
            
            return "Broadcast failed - system administrators notified"
    
    def is_admin(self, phone_number):
        """Check if user is admin"""
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
    
    def handle_incoming_message(self, from_phone, message_body, media_urls):
        """Handle incoming messages with smart reaction detection"""
        logger.info(f"📨 Incoming message from {from_phone}")
        
        try:
            from_phone = self.clean_phone_number(from_phone)
            message_body = message_body.strip() if message_body else ""
            
            # Log media if present
            if media_urls:
                logger.info(f"📎 Received {len(media_urls)} media files")
                for i, media in enumerate(media_urls):
                    logger.info(f"   Media {i+1}: {media.get('type', 'unknown')}")
            
            # Get member info - no auto-registration
            member = self.get_member_info(from_phone)
            
            if not member:
                logger.warning(f"❌ Rejected message from unregistered number: {from_phone}")
                # Send rejection message
                self.send_sms(
                    from_phone, 
                    "You are not registered in the church SMS system. Please contact a church administrator to be added."
                )
                return None
            
            logger.info(f"👤 Sender: {member['name']} (Admin: {member['is_admin']})")
            
            # CRITICAL: Detect reactions FIRST and handle silently
            reaction_data = self.detect_reaction_pattern(message_body)
            if reaction_data:
                logger.info(f"🔇 Silent reaction detected: {member['name']} reacted '{reaction_data['emoji']}'")
                
                # Find target message
                target_message = self.find_target_message_for_reaction(
                    reaction_data['target_message_fragment'], 
                    from_phone
                )
                
                if target_message:
                    # Store reaction silently - NO BROADCAST
                    success = self.store_reaction_silently(from_phone, reaction_data, target_message)
                    if success:
                        logger.info(f"✅ Reaction stored silently - will appear in next summary")
                        return None  # No response, no broadcast - completely silent
                    else:
                        logger.error(f"❌ Failed to store reaction silently")
                        return None
                else:
                    logger.warning(f"⚠️ Could not find target message for reaction")
                    return None  # Still silent even if target not found
            
            # Handle member commands
            if message_body.upper() == 'HELP':
                return ("📋 YESUWAY CHURCH SMS SYSTEM\n\n"
                       "✅ Send messages to entire congregation\n"
                       "✅ Share photos/videos (unlimited size)\n"
                       "✅ Clean media links (no technical details)\n"
                       "✅ Full quality preserved automatically\n"
                       "✅ Smart reaction tracking (silent)\n\n"
                       "📱 Text HELP for this message\n"
                       "🔇 Reactions tracked silently - summaries at 8 PM daily\n"
                       "🏛️ Production system - serving 24/7")
            
            # Default: Broadcast regular message
            logger.info(f"📡 Processing regular message broadcast...")
            return self.broadcast_message(from_phone, message_body, media_urls)
            
        except Exception as e:
            logger.error(f"❌ Message processing error: {e}")
            traceback.print_exc()
            return "Message processing temporarily unavailable - please try again"

# Initialize production system
logger.info("STARTING: Initializing Production Church SMS System with Smart Reaction Tracking...")
try:
    sms_system = ProductionChurchSMS()
    logger.info("SUCCESS: Production system with smart reaction tracking fully operational")
except Exception as e:
    logger.critical(f"CRITICAL: Production system failed to initialize: {e}")
    if not DEVELOPMENT_MODE:
        raise

def setup_production_congregation():
    """Setup production congregation with registered members"""
    logger.info("🔧 Setting up production congregation...")
    
    try:
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
        
        logger.info("✅ Production congregation setup completed with smart reaction tracking")
        
    except Exception as e:
        logger.error(f"❌ Production setup error: {e}")
        traceback.print_exc()

# ===== FLASK ROUTES =====

@app.route('/webhook/sms', methods=['POST'])
def handle_sms_webhook():
    """SMS webhook handler with smart reaction detection"""
    request_start = time.time()
    request_id = str(uuid.uuid4())[:8]
    
    logger.info(f"🌐 [{request_id}] SMS webhook called")
    
    try:
        # Extract webhook data
        from_number = request.form.get('From', '').strip()
        message_body = request.form.get('Body', '').strip()
        num_media = int(request.form.get('NumMedia', 0))
        message_sid = request.form.get('MessageSid', '')
        
        logger.info(f"📨 [{request_id}] From: {from_number}, Body: '{message_body}', Media: {num_media}")
        
        if not from_number:
            logger.warning(f"⚠️ [{request_id}] Missing From number")
            return "OK", 200
        
        # Extract media URLs
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
        
        # Process message asynchronously
        def process_async():
            try:
                response = sms_system.handle_incoming_message(
                    from_number, message_body, media_urls
                )
                
                # Send response if needed (reactions return None - no response)
                if response and sms_system.is_admin(from_number):
                    result = sms_system.send_sms(from_number, response)
                    if result['success']:
                        logger.info(f"📤 [{request_id}] Response sent: {result['sid']}")
                    else:
                        logger.error(f"❌ [{request_id}] Response failed: {result['error']}")
                
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
    """Handle delivery status callbacks from Twilio"""
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

@app.route('/health', methods=['GET'])
def health_check():
    """Production health check with smart reaction tracking"""
    try:
        health_data = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "Production Church SMS System with Smart Reaction Tracking v3.0",
            "environment": "production"
        }
        
        # Test database
        conn = sqlite3.connect('production_church.db', timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM members WHERE active = 1")
        member_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM broadcast_messages WHERE sent_at > datetime('now', '-24 hours') AND is_reaction = 0")
        recent_messages = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM message_reactions WHERE created_at > datetime('now', '-24 hours')")
        recent_reactions = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM media_files WHERE upload_status = 'completed'")
        media_count = cursor.fetchone()[0]
        conn.close()
        
        health_data["database"] = {
            "status": "connected",
            "active_members": member_count,
            "recent_messages_24h": recent_messages,
            "recent_reactions_24h": recent_reactions,
            "processed_media": media_count
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
        
        health_data["smart_reaction_system"] = {
            "status": "active",
            "silent_tracking": "enabled",
            "daily_summary_time": "8:00 PM",
            "pause_summary_trigger": "30 minutes silence",
            "recent_reactions_24h": recent_reactions
        }
        
        health_data["features"] = {
            "clean_media_display": "enabled",
            "manual_registration_only": "enabled",
            "auto_registration": "disabled",
            "smart_reaction_tracking": "enabled",
            "admin_commands": "disabled"
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
def home():
    """Production home page with smart reaction tracking"""
    try:
        conn = sqlite3.connect('production_church.db', timeout=5.0)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM members WHERE active = 1")
        member_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM broadcast_messages WHERE sent_at > datetime('now', '-24 hours') AND is_reaction = 0")
        messages_24h = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM message_reactions WHERE created_at > datetime('now', '-24 hours')")
        reactions_24h = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM media_files WHERE upload_status = 'completed'")
        media_processed = cursor.fetchone()[0]
        
        conn.close()
        
        return f"""
🏛️ YesuWay Church SMS Broadcasting System
📅 Production Environment - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🚀 PRODUCTION STATUS: SMART REACTION TRACKING ACTIVE

📊 LIVE STATISTICS:
✅ Registered Members: {member_count}
✅ Messages (24h): {messages_24h}
✅ Silent Reactions (24h): {reactions_24h}
✅ Media Files Processed: {media_processed}
✅ Church Number: {TWILIO_PHONE_NUMBER}

🔇 SMART REACTION SYSTEM:
✅ SILENT TRACKING - No reaction spam to congregation
✅ DAILY SUMMARIES - Sent every day at 8:00 PM
✅ PAUSE SUMMARIES - After 30 minutes of conversation silence
✅ INDUSTRY PATTERNS - Detects all major reaction formats
✅ SMART MATCHING - Links reactions to correct messages

🛡️ SECURITY FEATURES:
✅ REGISTERED MEMBERS ONLY
✅ No auto-registration
✅ Manual member management (database only)
✅ Unknown numbers rejected
✅ No SMS admin commands

🧹 CLEAN MEDIA SYSTEM:
✅ Professional presentation
✅ Simple "Photo 1", "Video 1" display
✅ No technical details shown
✅ Direct media viewing

🎯 CORE FEATURES:
✅ Smart media processing
✅ Unlimited file sizes
✅ Clean public links
✅ Professional broadcasting
✅ Comprehensive error handling

📱 MEMBER EXPERIENCE:
• Only registered members can send
• Unknown numbers receive rejection
• Large files become clean links
• Reactions tracked silently
• Daily summaries of engagement
• Professional presentation

🕐 REACTION SUMMARY SCHEDULE:
• Daily at 8:00 PM - Top reacted messages
• After 30min silence - Recent activity

🎯 RESULT: Zero reaction spam + Full engagement tracking!

💚 SERVING YOUR CONGREGATION 24/7 - SMART & SILENT
        """
        
    except Exception as e:
        logger.error(f"❌ Home page error: {e}")
        return f"❌ System temporarily unavailable: {e}", 500

@app.route('/test', methods=['GET', 'POST'])
def test_endpoint():
    """Test endpoint with reaction pattern testing"""
    try:
        if request.method == 'POST':
            from_number = request.form.get('From', '+1234567890')
            message_body = request.form.get('Body', 'test message')
            
            logger.info(f"🧪 Test message: {from_number} -> {message_body}")
            
            # Test reaction detection
            reaction_data = sms_system.detect_reaction_pattern(message_body)
            
            def test_async():
                result = sms_system.handle_incoming_message(from_number, message_body, [])
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
                "smart_reaction_system": "active",
                "admin_commands": "disabled"
            })
        
        else:
            return jsonify({
                "status": "✅ Test endpoint active",
                "method": "GET",
                "features": ["Clean media display", "Manual registration only", "Smart reaction tracking", "No admin commands"],
                "reaction_patterns": [
                    "Loved \"message text\"",
                    "Laughed at \"message text\"", 
                    "Emphasized \"message text\"",
                    "Reacted 😍 to \"message text\"",
                    "❤️",
                    "😂"
                ],
                "test_examples": [
                    "curl -X POST /test -d 'From=+1234567890&Body=Loved \"test message\"'",
                    "curl -X POST /test -d 'From=+1234567890&Body=😂'"
                ],
                "usage": "POST with From and Body parameters to test reaction detection"
            })
            
    except Exception as e:
        logger.error(f"❌ Test endpoint error: {e}")
        return jsonify({"error": str(e)}), 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint not found", 
        "status": "production",
        "available_endpoints": ["/", "/health", "/webhook/sms", "/test"]
    }), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"❌ Internal server error: {error}")
    return jsonify({
        "error": "Internal server error", 
        "status": "production"
    }), 500

# Request monitoring
@app.before_request
def before_request():
    request.start_time = time.time()

@app.after_request
def after_request(response):
    if hasattr(request, 'start_time'):
        duration = round((time.time() - request.start_time) * 1000, 2)
        if duration > 1000:
            logger.warning(f"⏰ Slow request: {request.endpoint} took {duration}ms")
        
        try:
            if hasattr(sms_system, 'record_performance_metric'):
                endpoint = request.endpoint or 'unknown'
                sms_system.record_performance_metric(f'http_{endpoint}', int(duration), response.status_code < 400)
        except:
            pass
    
    return response

if __name__ == '__main__':
    logger.info("STARTING: Production Church SMS System with Smart Reaction Tracking...")
    logger.info("INFO: Professional church communication platform")
    logger.info("INFO: Clean media presentation enabled")
    logger.info("INFO: Manual registration only - secure access")
    logger.info("INFO: Smart reaction tracking - silent with summaries")
    logger.info("INFO: Daily summaries at 8:00 PM")
    logger.info("INFO: Pause summaries after 30min silence")
    logger.info("INFO: Auto-registration disabled")
    logger.info("INFO: SMS admin commands disabled")
    
    if DEVELOPMENT_MODE:
        logger.info("DEVELOPMENT MODE: Running with mock services for testing")
    
    # Validate environment for production
    if not DEVELOPMENT_MODE:
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
            logger.critical("CRITICAL: Missing Twilio credentials")
            raise SystemExit("Production requires all Twilio credentials")
        
        if not all([R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL]):
            logger.critical("CRITICAL: Missing R2 credentials")
            raise SystemExit("Production requires all R2 credentials")
    
    # Setup congregation
    setup_production_congregation()
    
    logger.info("SUCCESS: Production Church SMS System: READY FOR PURE MESSAGING")
    logger.info("INFO: Webhook endpoint: /webhook/sms")
    logger.info("INFO: Health monitoring: /health") 
    logger.info("INFO: System overview: /")
    logger.info("INFO: Test endpoint: /test")
    logger.info("INFO: Enterprise-grade system active")
    logger.info("INFO: Clean media display enabled")
    logger.info("INFO: Secure member registration (database only)")
    logger.info("INFO: Smart reaction tracking active")
    logger.info("INFO: Reaction summaries: Daily 8 PM + 30min pause")
    logger.info("INFO: Admin commands completely removed")
    logger.info("INFO: Serving YesuWay Church congregation")
    
    # Run production server
    port = int(os.environ.get('PORT', 5000))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=DEVELOPMENT_MODE,
        threaded=True,
        use_reloader=False
    )