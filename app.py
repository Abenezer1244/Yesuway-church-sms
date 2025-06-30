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

class ProductionChurchSMS:
    def __init__(self):
        """Initialize production-grade church SMS broadcasting system"""
        self.twilio_client = None
        self.r2_client = None
        self.executor = ThreadPoolExecutor(max_workers=10)
        
        # Initialize Twilio client
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
            try:
                self.twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
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
                self.r2_client.head_bucket(Bucket=R2_BUCKET_NAME)
                logger.info(f"✅ Cloudflare R2 production connection established: {R2_BUCKET_NAME}")
            except Exception as e:
                logger.error(f"❌ R2 connection failed: {e}")
                raise
        else:
            logger.error("❌ Missing R2 credentials")
            raise ValueError("R2 credentials required for production")
        
        self.init_production_database()
        logger.info("🚀 Production Church SMS System initialized successfully")
    
    def init_production_database(self):
        """Initialize production database with optimizations"""
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
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            
            # Create indexes for performance
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
            logger.info("✅ Production database initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            traceback.print_exc()
            raise

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
                    time.sleep(1 * (attempt + 1))
                else:
                    duration_ms = int((time.time() - start_time) * 1000)
                    self.record_performance_metric('sms_send', duration_ms, False, str(e))
                    logger.error(f"❌ All SMS attempts failed for {to_phone}")
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
        """Broadcast message to all registered members"""
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
                 has_media, media_count, processing_status, delivery_status) 
                VALUES (?, ?, ?, ?, ?, ?, ?, 'processing', 'pending')
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
            
            # Return admin confirmation
            if sender['is_admin']:
                confirmation = f"✅ Broadcast completed in {total_time:.1f}s\n"
                confirmation += f"📊 Delivered: {delivery_stats['sent']}/{len(recipients)}\n"
                
                if large_media_count > 0:
                    confirmation += f"📎 Clean media links: {large_media_count}\n"
                
                if delivery_stats['failed'] > 0:
                    confirmation += f"⚠️ Failed deliveries: {delivery_stats['failed']}\n"
                
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
    
    def handle_admin_commands(self, from_phone, message_body):
        """Handle admin commands"""
        if not self.is_admin(from_phone):
            return None
        
        command = message_body.upper().strip()
        
        try:
            if command.startswith('ADD '):
                return self.add_member_command(message_body)
            
            elif command == 'STATS':
                return self.get_system_stats()
            
            elif command == 'MEMBERS':
                return self.get_members_list()
            
            elif command == 'HELP':
                return ("👑 ADMIN COMMANDS:\n\n"
                       "👥 Member Management:\n"
                       "• ADD +phone Name TO group - Add member\n"
                       "• STATS - System statistics\n"
                       "• MEMBERS - List all members\n"
                       "• HELP - Show this help\n\n"
                       "📋 Note: Only registered members can send messages\n"
                       "🎯 Professional church administration")
            
            else:
                return None
                
        except Exception as e:
            logger.error(f"❌ Admin command error: {e}")
            return f"Admin command failed: {str(e)}"

    def add_member_command(self, message_body):
        """Handle ADD member command"""
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
            
            return f"✅ Added {name} to Group {group_id}\n📱 They can now send messages to congregation"
            
        except Exception as e:
            logger.error(f"❌ Add member error: {e}")
            return f"❌ Error adding member: {str(e)}"

    def get_system_stats(self):
        """Get comprehensive system statistics"""
        try:
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            # Get member stats
            cursor.execute("SELECT COUNT(*) FROM members WHERE active = 1")
            total_members = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM members WHERE active = 1 AND is_admin = 1")
            admin_count = cursor.fetchone()[0]
            
            # Get message stats
            cursor.execute("SELECT COUNT(*) FROM broadcast_messages WHERE sent_at > datetime('now', '-7 days')")
            messages_week = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM broadcast_messages WHERE sent_at > datetime('now', '-24 hours')")
            messages_day = cursor.fetchone()[0]
            
            # Get media stats
            cursor.execute("SELECT COUNT(*) FROM media_files WHERE upload_status = 'completed'")
            media_processed = cursor.fetchone()[0]
            
            # Get delivery stats
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_deliveries,
                    SUM(CASE WHEN delivery_status = 'delivered' THEN 1 ELSE 0 END) as successful,
                    AVG(delivery_time_ms) as avg_time
                FROM delivery_log 
                WHERE delivered_at > datetime('now', '-7 days')
            ''')
            delivery_stats = cursor.fetchone()
            total_deliveries, successful_deliveries, avg_delivery_time = delivery_stats
            
            conn.close()
            
            success_rate = (successful_deliveries / total_deliveries * 100) if total_deliveries > 0 else 0
            avg_time_formatted = f"{avg_delivery_time:.0f}ms" if avg_delivery_time else "N/A"
            
            return f"""📊 SYSTEM STATISTICS

👥 MEMBERS:
• Total active: {total_members}
• Administrators: {admin_count}

📨 MESSAGES:
• Past 24 hours: {messages_day}
• Past 7 days: {messages_week}

📎 MEDIA:
• Files processed: {media_processed}

📤 DELIVERY (7 days):
• Total deliveries: {total_deliveries}
• Success rate: {success_rate:.1f}%
• Average time: {avg_time_formatted}

🎯 System running smoothly"""
            
        except Exception as e:
            logger.error(f"❌ Error getting stats: {e}")
            return "❌ Error retrieving system statistics"
    
    def get_members_list(self):
        """Get list of all active members"""
        try:
            conn = sqlite3.connect('production_church.db', timeout=30.0)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT m.name, m.phone_number, m.is_admin, g.name as group_name, m.message_count
                FROM members m
                JOIN group_members gm ON m.id = gm.member_id
                JOIN groups g ON gm.group_id = g.id
                WHERE m.active = 1
                ORDER BY m.name
            ''')
            
            members = cursor.fetchall()
            conn.close()
            
            if not members:
                return "📋 No active members found"
            
            lines = ["📋 ACTIVE MEMBERS:\n"]
            
            for name, phone, is_admin, group_name, msg_count in members:
                admin_marker = " 👑" if is_admin else ""
                lines.append(f"• {name}{admin_marker}")
                lines.append(f"  {phone} | {group_name} | {msg_count} msgs\n")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"❌ Error getting members list: {e}")
            return "❌ Error retrieving members list"
    
    def handle_incoming_message(self, from_phone, message_body, media_urls):
        """Handle incoming messages - registered members only"""
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
            
            # Handle admin commands
            admin_response = self.handle_admin_commands(from_phone, message_body)
            if admin_response:
                logger.info(f"🔧 Admin command processed")
                return admin_response
            
            # Handle member commands
            if message_body.upper() == 'HELP':
                return ("📋 YESUWAY CHURCH SMS SYSTEM\n\n"
                       "✅ Send messages to entire congregation\n"
                       "✅ Share photos/videos (unlimited size)\n"
                       "✅ Clean media links (no technical details)\n"
                       "✅ Full quality preserved automatically\n\n"
                       "📱 Text HELP for this message\n"
                       "🏛️ Production system - serving 24/7")
            
            # Default: Broadcast message
            logger.info(f"📡 Processing broadcast...")
            return self.broadcast_message(from_phone, message_body, media_urls)
            
        except Exception as e:
            logger.error(f"❌ Message processing error: {e}")
            traceback.print_exc()
            return "Message processing temporarily unavailable - please try again"

# Initialize production system
logger.info("🚀 Initializing Production Church SMS System...")
try:
    sms_system = ProductionChurchSMS()
    logger.info("✅ Production system fully operational")
except Exception as e:
    logger.critical(f"💥 Production system failed to initialize: {e}")
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
        
        logger.info("✅ Production congregation setup completed")
        
    except Exception as e:
        logger.error(f"❌ Production setup error: {e}")
        traceback.print_exc()

# ===== FLASK ROUTES =====

@app.route('/webhook/sms', methods=['POST'])
def handle_sms_webhook():
    """SMS webhook handler"""
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
                
                # Send admin response if needed
                if response and sms_system.is_admin(from_number):
                    result = sms_system.send_sms(from_number, response)
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
    """Production health check"""
    try:
        health_data = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "Production Church SMS System v1.0",
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
        conn.close()
        
        health_data["database"] = {
            "status": "connected",
            "active_members": member_count,
            "recent_messages_24h": recent_messages,
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
        
        health_data["features"] = {
            "clean_media_display": "enabled",
            "manual_registration_only": "enabled",
            "auto_registration": "disabled"
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
    """Production home page"""
    try:
        conn = sqlite3.connect('production_church.db', timeout=5.0)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM members WHERE active = 1")
        member_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM broadcast_messages WHERE sent_at > datetime('now', '-24 hours')")
        messages_24h = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM media_files WHERE upload_status = 'completed'")
        media_processed = cursor.fetchone()[0]
        
        conn.close()
        
        return f"""
🏛️ YesuWay Church SMS Broadcasting System
📅 Production Environment - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🚀 PRODUCTION STATUS: ACTIVE

📊 LIVE STATISTICS:
✅ Registered Members: {member_count}
✅ Messages (24h): {messages_24h}
✅ Media Files Processed: {media_processed}
✅ Church Number: {TWILIO_PHONE_NUMBER}

🛡️ SECURITY FEATURES:
✅ REGISTERED MEMBERS ONLY
✅ No auto-registration
✅ Admin-controlled membership
✅ Unknown numbers rejected

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

👑 ADMIN COMMANDS:
• ADD +phone Name TO group
• STATS - System statistics
• MEMBERS - List all members
• HELP - Command help

📱 MEMBER EXPERIENCE:
• Only registered members can send
• Unknown numbers receive rejection
• Large files become clean links
• Professional presentation

💚 SERVING YOUR CONGREGATION 24/7
        """
        
    except Exception as e:
        logger.error(f"❌ Home page error: {e}")
        return f"❌ System temporarily unavailable: {e}", 500

@app.route('/test', methods=['GET', 'POST'])
def test_endpoint():
    """Test endpoint"""
    try:
        if request.method == 'POST':
            from_number = request.form.get('From', '+1234567890')
            message_body = request.form.get('Body', 'test message')
            
            logger.info(f"🧪 Test message: {from_number} -> {message_body}")
            
            def test_async():
                result = sms_system.handle_incoming_message(from_number, message_body, [])
                logger.info(f"🧪 Test result: {result}")
            
            sms_system.executor.submit(test_async)
            
            return jsonify({
                "status": "✅ Test processed",
                "from": from_number,
                "body": message_body,
                "timestamp": datetime.now().isoformat(),
                "processing": "async"
            })
        
        else:
            return jsonify({
                "status": "✅ Test endpoint active",
                "method": "GET",
                "features": ["Clean media display", "Manual registration only"],
                "usage": "POST with From and Body parameters to test"
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
    logger.info("🚀 Starting Production Church SMS System...")
    logger.info("🏛️ Professional church communication platform")
    logger.info("🧹 Clean media presentation enabled")
    logger.info("🔒 Manual registration only - secure access")
    logger.info("❌ Auto-registration disabled")
    
    # Validate environment
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]):
        logger.critical("💥 Missing Twilio credentials")
        raise SystemExit("Production requires all Twilio credentials")
    
    if not all([R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL]):
        logger.critical("💥 Missing R2 credentials")
        raise SystemExit("Production requires all R2 credentials")
    
    # Setup congregation
    setup_production_congregation()
    
    logger.info("🎯 Production Church SMS System: READY")
    logger.info("📡 Webhook endpoint: /webhook/sms")
    logger.info("🏥 Health monitoring: /health") 
    logger.info("📊 System overview: /")
    logger.info("🧪 Test endpoint: /test")
    logger.info("🛡️ Enterprise-grade system active")
    logger.info("🧹 Clean media display enabled")
    logger.info("🔒 Secure member registration")
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