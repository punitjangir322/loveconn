from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, send_file
from flask_socketio import SocketIO, emit
import mysql.connector
import os
import uuid
from datetime import datetime, timedelta, date
import json
import base64
from io import BytesIO
import qrcode
import eventlet

app = Flask(__name__)
app.secret_key = 'loveconnect_secret_key_2024_mobile_app'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Active users tracking
active_users = {}

# MySQL Database Configuration
def get_db_connection():
    try:
        return mysql.connector.connect(
            host="localhost",
            user="root", 
            password="12345",
            database="loveconnect_db",
            auth_plugin='mysql_native_password'
        )
    except mysql.connector.Error:
        # If database doesn't exist, create it
        conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="12345"
        )
        cursor = conn.cursor()
        cursor.execute("CREATE DATABASE IF NOT EXISTS loveconnect_db")
        cursor.close()
        conn.close()
        
        return mysql.connector.connect(
            host="localhost",
            user="root", 
            password="12345",
            database="loveconnect_db",
            auth_plugin='mysql_native_password'
        )

# Database setup
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("USE loveconnect_db")
    
    # Users table
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INT AUTO_INCREMENT PRIMARY KEY,
                  name VARCHAR(255) NOT NULL,
                  mobile VARCHAR(15) NOT NULL,
                  age INT NOT NULL,
                  gender VARCHAR(10) NOT NULL,
                  username VARCHAR(50) UNIQUE NOT NULL,
                  password VARCHAR(255) NOT NULL,
                  image LONGBLOB,
                  is_verified BOOLEAN DEFAULT FALSE,
                  is_premium BOOLEAN DEFAULT FALSE,
                  premium_expiry DATETIME,
                  is_blocked BOOLEAN DEFAULT FALSE,
                  free_messages INT DEFAULT 10,
                  last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  is_online BOOLEAN DEFAULT FALSE,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Matches table
    cursor.execute('''CREATE TABLE IF NOT EXISTS matches
                 (id INT AUTO_INCREMENT PRIMARY KEY,
                  user1_id INT,
                  user2_id INT,
                  status VARCHAR(20),
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Likes table
    cursor.execute('''CREATE TABLE IF NOT EXISTS likes
                 (id INT AUTO_INCREMENT PRIMARY KEY,
                  liker_id INT,
                  liked_id INT,
                  status VARCHAR(20),
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Messages table
    cursor.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INT AUTO_INCREMENT PRIMARY KEY,
                  sender_id INT,
                  receiver_id INT,
                  message TEXT,
                  is_read BOOLEAN DEFAULT FALSE,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Payments table
    cursor.execute('''CREATE TABLE IF NOT EXISTS payments
                 (id INT AUTO_INCREMENT PRIMARY KEY,
                  user_id INT,
                  txn_id VARCHAR(100),
                  amount DECIMAL(10,2),
                  status VARCHAR(20),
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Notifications table
    cursor.execute('''CREATE TABLE IF NOT EXISTS notifications
                 (id INT AUTO_INCREMENT PRIMARY KEY,
                  user_id INT,
                  message TEXT,
                  is_read BOOLEAN DEFAULT FALSE,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Add admin user if not exists
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (name, mobile, age, gender, username, password, is_verified) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                      ('Admin', '0000000000', 30, 'Other', 'admin', 'admin123', True))
    
    # Add sample users
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] <= 1:
        sample_users = [
            ('Emma Wilson', '9876543210', 25, 'Female', 'emma25', 'password123', None, True, False, None, False, 10),
            ('James Smith', '9876543211', 28, 'Male', 'james28', 'password123', None, True, True, '2024-12-31 23:59:59', False, 10),
            ('Sophia Brown', '9876543212', 26, 'Female', 'sophia26', 'password123', None, True, False, None, False, 10),
            ('Michael Johnson', '9876543213', 30, 'Male', 'mike30', 'password123', None, True, False, None, False, 10),
            ('Olivia Davis', '9876543214', 24, 'Female', 'olivia24', 'password123', None, True, True, '2024-11-30 23:59:59', False, 10)
        ]
        cursor.executemany("INSERT INTO users (name, mobile, age, gender, username, password, image, is_verified, is_premium, premium_expiry, is_blocked, free_messages) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", sample_users)
    
    conn.commit()
    cursor.close()
    conn.close()

# Initialize database
init_db()

# Helper functions
def get_user_by_username(username):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user

def get_user_by_id(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user

def get_all_users():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute('''
        SELECT u.* FROM users u 
        WHERE u.id != %s 
        AND u.is_blocked = FALSE 
        AND u.id NOT IN (
            SELECT liked_id FROM likes WHERE liker_id = %s
        )
    ''', (session.get('user_id'), session.get('user_id')))
    
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return users

def check_match(user1_id, user2_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM matches WHERE (user1_id = %s AND user2_id = %s) OR (user1_id = %s AND user2_id = %s)",
                  (user1_id, user2_id, user2_id, user1_id))
    match = cursor.fetchone()
    cursor.close()
    conn.close()
    return match

def get_matches(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT u.id, u.name, u.image, u.is_online, u.last_seen,
               (SELECT message FROM messages 
                WHERE (sender_id = u.id AND receiver_id = %s) OR (sender_id = %s AND receiver_id = u.id)
                ORDER BY timestamp DESC LIMIT 1) as last_message,
               (SELECT timestamp FROM messages 
                WHERE (sender_id = u.id AND receiver_id = %s) OR (sender_id = %s AND receiver_id = u.id)
                ORDER BY timestamp DESC LIMIT 1) as last_message_time
        FROM users u 
        JOIN matches m ON (m.user1_id = u.id OR m.user2_id = u.id) 
        WHERE (m.user1_id = %s OR m.user2_id = %s) AND u.id != %s AND m.status = 'matched'
        ORDER BY last_message_time DESC 
    ''', (user_id, user_id, user_id, user_id, user_id, user_id, user_id))
    matches = cursor.fetchall()
    cursor.close()
    conn.close()
    return matches

def get_messages(user1_id, user2_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''SELECT m.*, u.name as sender_name FROM messages m 
                 JOIN users u ON m.sender_id = u.id 
                 WHERE (sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s)
                 ORDER BY timestamp''',
              (user1_id, user2_id, user2_id, user1_id))
    messages = cursor.fetchall()
    cursor.close()
    conn.close()
    return messages

def get_unread_message_count(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''SELECT COUNT(*) as count FROM messages 
                   WHERE receiver_id = %s AND is_read = FALSE''', (user_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result['count'] if result else 0

def get_unread_message_count_with_user(user_id, other_user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''SELECT COUNT(*) as count FROM messages 
                   WHERE receiver_id = %s AND sender_id = %s AND is_read = FALSE''', 
                   (user_id, other_user_id))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result['count'] if result else 0

def mark_messages_as_read(user1_id, user2_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''UPDATE messages SET is_read = TRUE 
                   WHERE sender_id = %s AND receiver_id = %s AND is_read = FALSE''',
                   (user2_id, user1_id))
    conn.commit()
    cursor.close()
    conn.close()

def get_last_message(user1_id, user2_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''SELECT message, timestamp FROM messages 
                   WHERE (sender_id = %s AND receiver_id = %s) OR (sender_id = %s AND receiver_id = %s)
                   ORDER BY timestamp DESC LIMIT 1''',
                   (user1_id, user2_id, user2_id, user1_id))
    message = cursor.fetchone()
    cursor.close()
    conn.close()
    return message

def update_user_online_status(user_id, is_online=True):
    conn = get_db_connection()
    cursor = conn.cursor()
    if is_online:
        cursor.execute("UPDATE users SET is_online = TRUE, last_seen = CURRENT_TIMESTAMP WHERE id = %s", (user_id,))
    else:
        cursor.execute("UPDATE users SET is_online = FALSE, last_seen = CURRENT_TIMESTAMP WHERE id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()

def is_premium_active(user_id):
    user = get_user_by_id(user_id)
    if user and user['is_premium'] and user['premium_expiry']:
        expiry_date = user['premium_expiry']
        
        if isinstance(expiry_date, str):
            expiry_date = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
        elif isinstance(expiry_date, date) and not isinstance(expiry_date, datetime):
            expiry_date = datetime.combine(expiry_date, datetime.min.time())
        
        return expiry_date > datetime.now()
    return False

def get_premium_days_left(user_id):
    user = get_user_by_id(user_id)
    if user and user['is_premium'] and user['premium_expiry']:
        expiry_date = user['premium_expiry']
        
        if isinstance(expiry_date, str):
            expiry_date = datetime.strptime(expiry_date, '%Y-%m-%d %H:%M:%S')
        elif isinstance(expiry_date, date) and not isinstance(expiry_date, datetime):
            expiry_date = datetime.combine(expiry_date, datetime.min.time())
        
        days_left = (expiry_date - datetime.now()).days
        return max(0, days_left)
    return 0

def get_notifications(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC LIMIT 10", (user_id,))
    notifications = cursor.fetchall()
    cursor.close()
    conn.close()
    return notifications

def get_unread_notifications_count(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) as count FROM notifications WHERE user_id = %s AND is_read = FALSE", (user_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result['count'] if result else 0

def add_notification(user_id, message):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO notifications (user_id, message) VALUES (%s, %s)", (user_id, message))
    conn.commit()
    cursor.close()
    conn.close()

def mark_notification_read(notification_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET is_read = TRUE WHERE id = %s", (notification_id,))
    conn.commit()
    cursor.close()
    conn.close()

def generate_qr_code(upi_id, amount):
    upi_url = f"upi://pay?pa={upi_id}&pn=LoveConnect&am={amount}&cu=INR&tn=LoveConnect Premium Subscription"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(upi_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return img_str

def get_likes_received(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT l.*, u.name as liker_name, u.username as liker_username 
        FROM likes l 
        JOIN users u ON l.liker_id = u.id 
        WHERE l.liked_id = %s AND l.status = 'liked'
        AND l.liker_id NOT IN (SELECT liked_id FROM likes WHERE liker_id = %s AND status = 'liked')
    ''', (user_id, user_id))
    likes = cursor.fetchall()
    cursor.close()
    conn.close()
    return likes

def search_users(search_term):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT * FROM users 
        WHERE (name LIKE %s OR username LIKE %s OR mobile LIKE %s OR gender LIKE %s)
        AND id != 0
    ''', (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%', f'%{search_term}%'))
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return users

def search_payments(search_term):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT p.*, u.name as user_name 
        FROM payments p 
        JOIN users u ON p.user_id = u.id 
        WHERE p.txn_id LIKE %s OR u.name LIKE %s OR u.username LIKE %s
    ''', (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%'))
    payments = cursor.fetchall()
    cursor.close()
    conn.close()
    return payments

def get_user_payment_info(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT p.*, u.name as user_name, u.username, u.is_premium, u.premium_expiry
        FROM payments p 
        JOIN users u ON p.user_id = u.id 
        WHERE p.user_id = %s 
        ORDER BY p.created_at DESC 
        LIMIT 1
    ''', (user_id,))
    payment_info = cursor.fetchone()
    cursor.close()
    conn.close()
    return payment_info

def get_all_payments():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute('''
        SELECT p.*, u.name as user_name, u.username, u.is_premium, u.premium_expiry
        FROM payments p 
        JOIN users u ON p.user_id = u.id 
        ORDER BY p.created_at DESC
    ''')
    payments = cursor.fetchall()
    cursor.close()
    conn.close()
    return payments

# Socket.IO Events
@socketio.on('connect')
def handle_connect():
    if 'user_id' in session and not session.get('is_admin'):
        user_id = session['user_id']
        active_users[user_id] = request.sid
        update_user_online_status(user_id, True)
        
        # Notify all matches about online status
        matches = get_matches(user_id)
        for match in matches:
            if match['id'] in active_users:
                emit('user_online', {'user_id': user_id}, room=active_users[match['id']])
        
        print(f"User {user_id} connected with socket {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session and not session.get('is_admin'):
        user_id = session['user_id']
        if user_id in active_users:
            del active_users[user_id]
        update_user_online_status(user_id, False)
        
        # Notify all matches about offline status
        matches = get_matches(user_id)
        for match in matches:
            if match['id'] in active_users:
                emit('user_offline', {'user_id': user_id}, room=active_users[match['id']])
        
        print(f"User {user_id} disconnected")

@socketio.on('send_message')
def handle_send_message(data):
    if 'user_id' not in session or session.get('is_admin'):
        return
    
    sender_id = session['user_id']
    receiver_id = data.get('receiver_id')
    message_text = data.get('message')
    
    if not receiver_id or not message_text:
        return
    
    # Save message to database
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("INSERT INTO messages (sender_id, receiver_id, message) VALUES (%s, %s, %s)",
                  (sender_id, receiver_id, message_text))
    
    message_id = cursor.lastrowid
    
    # Get sender info
    cursor.execute("SELECT name FROM users WHERE id = %s", (sender_id,))
    sender = cursor.fetchone()
    
    conn.commit()
    cursor.close()
    conn.close()
    
    # Prepare message data for real-time delivery
    message_data = {
        'id': message_id,
        'sender_id': sender_id,
        'receiver_id': receiver_id,
        'message': message_text,
        'sender_name': sender[0] if sender else 'Unknown',
        'timestamp': datetime.now().strftime('%H:%M')
    }
    
    # Send to receiver if online
    if receiver_id in active_users:
        emit('receive_message', message_data, room=active_users[receiver_id])
        emit('update_match_list', {}, room=active_users[receiver_id])
    
    # Send back to sender for their own UI update
    emit('message_sent', message_data, room=request.sid)
    emit('update_match_list', {}, room=request.sid)

@socketio.on('typing_start')
def handle_typing_start(data):
    receiver_id = data.get('receiver_id')
    if receiver_id and receiver_id in active_users:
        emit('user_typing', {'user_id': session['user_id']}, room=active_users[receiver_id])

@socketio.on('typing_stop')
def handle_typing_stop(data):
    receiver_id = data.get('receiver_id')
    if receiver_id and receiver_id in active_users:
        emit('user_stop_typing', {'user_id': session['user_id']}, room=active_users[receiver_id])

@socketio.on('mark_messages_read')
def handle_mark_messages_read(data):
    user1_id = session['user_id']
    user2_id = data.get('other_user_id')
    
    if user2_id:
        mark_messages_as_read(user1_id, user2_id)
        
        # Notify the other user that messages were read
        if user2_id in active_users:
            emit('messages_read', {'user_id': user1_id}, room=active_users[user2_id])

# HTML TEMPLATES
LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LoveConnect - Login</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#ff4b7d">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        
        .container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 30px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
        }
        
        .logo {
            text-align: center;
            margin-bottom: 30px;
        }
        
        .logo h1 {
            color: #ff4b7d;
            font-size: 2.5em;
            font-weight: 800;
            margin-bottom: 10px;
        }
        
        .logo p {
            color: #666;
            font-size: 1.1em;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 600;
        }
        
        input, select {
            width: 100%;
            padding: 15px;
            border: 2px solid #e1e1e1;
            border-radius: 12px;
            font-size: 16px;
            transition: all 0.3s ease;
            background: white;
        }
        
        input:focus, select:focus {
            border-color: #ff4b7d;
            outline: none;
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(255, 75, 125, 0.2);
        }
        
        .btn {
            background: linear-gradient(135deg, #ff4b7d, #ff6b6b);
            color: white;
            border: none;
            padding: 15px;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(255, 75, 125, 0.3);
        }
        
        .btn:active {
            transform: scale(0.98);
            box-shadow: 0 2px 8px rgba(255, 75, 125, 0.3);
        }
        
        .links {
            text-align: center;
            margin-top: 20px;
        }
        
        .links a {
            color: #ff4b7d;
            text-decoration: none;
            font-weight: 600;
        }
        
        .error {
            background: #ffe6e6;
            color: #d63031;
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
            border: 1px solid #ffcccc;
        }
        
        .user-type {
            display: flex;
            background: #f8f9fa;
            border-radius: 12px;
            padding: 4px;
            margin-bottom: 20px;
        }
        
        .user-type input[type="radio"] {
            display: none;
        }
        
        .user-type label {
            flex: 1;
            text-align: center;
            padding: 12px;
            border-radius: 8px;
            cursor: pointer;
            margin: 0;
            transition: all 0.3s ease;
        }
        
        .user-type input[type="radio"]:checked + label {
            background: #ff4b7d;
            color: white;
        }
        
        .install-prompt {
            background: #28a745;
            color: white;
            padding: 15px;
            border-radius: 12px;
            text-align: center;
            margin-top: 20px;
            cursor: pointer;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">
            <h1>💖 LoveConnect</h1>
            <p>Find Your Perfect Match</p>
        </div>
        
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        
        <form method="POST">
            <div class="user-type">
                <input type="radio" id="user" name="user_type" value="user" checked>
                <label for="user">User</label>
                <input type="radio" id="admin" name="user_type" value="admin">
                <label for="admin">Admin</label>
            </div>
            
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required placeholder="Enter your username">
            </div>
            
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required placeholder="Enter your password">
            </div>
            
            <button type="submit" class="btn">Login</button>
            
            <div class="links">
                <a href="{{ url_for('register') }}">Create New Account</a>
            </div>
        </form>
        
        <div class="install-prompt" onclick="installApp()">
            📱 Install LoveConnect App
        </div>
    </div>

    <script>
        let deferredPrompt;
        
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            deferredPrompt = e;
        });
        
        async function installApp() {
            if (deferredPrompt) {
                deferredPrompt.prompt();
                const { outcome } = await deferredPrompt.userChoice;
                if (outcome === 'accepted') {
                    console.log('App installed successfully');
                }
                deferredPrompt = null;
            } else {
                alert('LoveConnect is already installed or cannot be installed on this device.');
            }
        }
        
        window.addEventListener('appinstalled', () => {
            console.log('LoveConnect was installed');
        });
    </script>
</body>
</html>
'''

REGISTER_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LoveConnect - Register</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#ff4b7d">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 25px;
            max-width: 500px;
            margin: 0 auto;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
        }
        
        .logo {
            text-align: center;
            margin-bottom: 25px;
        }
        
        .logo h1 {
            color: #ff4b7d;
            font-size: 2.2em;
            font-weight: 800;
            margin-bottom: 5px;
        }
        
        .logo p {
            color: #666;
            font-size: 1.1em;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        label {
            display: block;
            margin-bottom: 6px;
            color: #333;
            font-weight: 600;
            font-size: 14px;
        }
        
        input, select {
            width: 100%;
            padding: 14px;
            border: 2px solid #e1e1e1;
            border-radius: 10px;
            font-size: 16px;
            transition: all 0.3s ease;
            background: white;
        }
        
        input:focus, select:focus {
            border-color: #ff4b7d;
            outline: none;
        }
        
        .btn {
            background: linear-gradient(135deg, #ff4b7d, #ff6b6b);
            color: white;
            border: none;
            padding: 15px;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            transition: all 0.3s ease;
            margin-top: 10px;
        }
        
        .btn:active {
            transform: scale(0.98);
        }
        
        .links {
            text-align: center;
            margin-top: 20px;
        }
        
        .links a {
            color: #ff4b7d;
            text-decoration: none;
            font-weight: 600;
        }
        
        .error {
            background: #ffe6e6;
            color: #d63031;
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 15px;
            text-align: center;
            border: 1px solid #ffcccc;
        }
        
        .profile-image-preview {
            width: 80px;
            height: 80px;
            border-radius: 50%;
            background: #f8f9fa;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 15px;
            overflow: hidden;
            border: 3px solid #ff4b7d;
        }
        
        .profile-image-preview img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        
        .row {
            display: flex;
            gap: 10px;
        }
        
        .row .form-group {
            flex: 1;
        }
    </style>
    <script>
        function previewImage(event) {
            const input = event.target;
            const preview = document.getElementById('profile-preview');
            
            if (input.files && input.files[0]) {
                const reader = new FileReader();
                
                reader.onload = function(e) {
                    preview.innerHTML = '<img src="' + e.target.result + '" alt="Profile Preview">';
                }
                
                reader.readAsDataURL(input.files[0]);
            }
        }
    </script>
</head>
<body>
    <div class="container">
        <div class="logo">
            <h1>💖 LoveConnect</h1>
            <p>Create Your Account</p>
        </div>
        
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        
        <form method="POST" enctype="multipart/form-data">
            <div class="form-group">
                <div class="profile-image-preview" id="profile-preview">👤</div>
                <label for="image">Profile Image</label>
                <input type="file" id="image" name="image" accept="image/*" onchange="previewImage(event)">
            </div>
            
            <div class="form-group">
                <label for="name">Full Name</label>
                <input type="text" id="name" name="name" required placeholder="Enter your full name">
            </div>
            
            <div class="row">
                <div class="form-group">
                    <label for="mobile">Mobile Number</label>
                    <input type="tel" id="mobile" name="mobile" required pattern="[0-9]{10}" placeholder="10-digit number">
                </div>
                <div class="form-group">
                    <label for="age">Age</label>
                    <input type="number" id="age" name="age" min="18" max="100" required placeholder="Your age">
                </div>
            </div>
            
            <div class="form-group">
                <label for="gender">Gender</label>
                <select id="gender" name="gender" required>
                    <option value="">Select Gender</option>
                    <option value="Male">Male</option>
                    <option value="Female">Female</option>
                    <option value="Other">Other</option>
                </select>
            </div>
            
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required placeholder="Choose a username">
            </div>
            
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required placeholder="Create a password">
            </div>
            
            <button type="submit" class="btn">Create Account</button>
            
            <div class="links">
                <a href="{{ url_for('login') }}">Already have an account? Login</a>
            </div>
        </form>
    </div>
</body>
</html>
'''

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LoveConnect - Dashboard</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#ff4b7d">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f8f9fa;
            color: #333;
            line-height: 1.6;
        }
        
        .header {
            background: linear-gradient(135deg, #ff4b7d, #ff6b6b);
            color: white;
            padding: 20px 15px;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        
        .nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .logo h1 {
            font-size: 1.4em;
            font-weight: 700;
        }
        
        .nav-links {
            display: flex;
            gap: 15px;
        }
        
        .nav-links a {
            color: white;
            text-decoration: none;
            font-weight: 500;
            font-size: 0.9em;
        }
        
        .container {
            padding: 20px 15px;
            padding-bottom: 80px;
        }
        
        .welcome-card {
            background: white;
            border-radius: 20px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            text-align: center;
        }
        
        .welcome-card h2 {
            color: #ff4b7d;
            margin-bottom: 10px;
            font-size: 1.4em;
        }
        
        .premium-status {
            display: inline-block;
            padding: 6px 15px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: 600;
            margin-bottom: 15px;
        }
        
        .premium-active {
            background: linear-gradient(135deg, #ffd700, #ffa500);
            color: white;
        }
        
        .premium-inactive {
            background: #6c757d;
            color: white;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin: 20px 0;
        }
        
        .stat-item {
            text-align: center;
            padding: 15px 5px;
            background: #f8f9fa;
            border-radius: 12px;
        }
        
        .stat-number {
            font-size: 1.3em;
            font-weight: 700;
            color: #ff4b7d;
            display: block;
        }
        
        .stat-label {
            font-size: 0.8em;
            color: #666;
            margin-top: 5px;
        }
        
        .btn {
            background: linear-gradient(135deg, #ff4b7d, #ff6b6b);
            color: white;
            border: none;
            padding: 12px 25px;
            border-radius: 25px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-top: 10px;
            transition: all 0.3s ease;
        }
        
        .btn:active {
            transform: scale(0.95);
        }
        
        .features {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 15px;
            margin: 25px 0;
        }
        
        .feature-card {
            background: white;
            border-radius: 15px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
            text-decoration: none;
            color: inherit;
        }
        
        .feature-card:active {
            transform: scale(0.95);
        }
        
        .feature-icon {
            font-size: 2em;
            margin-bottom: 10px;
        }
        
        .feature-card h3 {
            font-size: 1.em;
            margin-bottom: 8px;
            color: #333;
        }
        
        .feature-card p {
            font-size: 0.8em;
            color: #666;
        }
        
        .premium-countdown {
            background: linear-gradient(135deg, #ffd700, #ffa500);
            color: white;
            border-radius: 20px;
            padding: 20px;
            margin-bottom: 20px;
            text-align: center;
        }
        
        .countdown-number {
            font-size: 2em;
            font-weight: 700;
            margin: 10px 0;
        }
        
        .likes-section, .notifications-section {
            background: white;
            border-radius: 20px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        
        .section-title {
            font-size: 1.1em;
            font-weight: 600;
            margin-bottom: 15px;
            color: #333;
        }
        
        .like-item, .notification-item {
            padding: 12px;
            border-bottom: 1px solid #f1f3f5;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .like-item:last-child, .notification-item:last-child {
            border-bottom: none;
        }
        
        .btn-like-back {
            background: #28a745;
            color: white;
            border: none;
            padding: 8px 15px;
            border-radius: 8px;
            font-size: 0.8em;
            cursor: pointer;
        }
        
        .bottom-nav {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: white;
            display: flex;
            justify-content: space-around;
            padding: 15px 0;
            box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
            z-index: 100;
        }
        
        .nav-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            text-decoration: none;
            color: #666;
            font-size: 0.8em;
            position: relative;
        }
        
        .nav-item.active {
            color: #ff4b7d;
        }
        
        .nav-icon {
            font-size: 1.2em;
            margin-bottom: 4px;
        }
        
        .badge {
            position: absolute;
            top: -5px;
            right: -5px;
            background: #ff4b7d;
            color: white;
            border-radius: 50%;
            width: 18px;
            height: 18px;
            font-size: 0.7em;
            display: flex;
            align-items: center;
            justify-content: center;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="nav">
            <div class="logo"><h1>💖 LoveConnect</h1></div>
            <div class="nav-links">
                <a href="{{ url_for('logout') }}">Logout</a>
            </div>
        </div>
    </div>
    
    <div class="container">
        <div class="welcome-card">
            <h2>Welcome, {{ user.name }}!</h2>
            <div class="premium-status {% if premium_active %}premium-active{% else %}premium-inactive{% endif %}">
                {% if premium_active %}PREMIUM ACTIVE - {{ days_left }} days left{% else %}PREMIUM INACTIVE{% endif %}
            </div>
            <p>Find your perfect match and start a meaningful connection</p>
            
            <div class="stats">
                <div class="stat-item">
                    <span class="stat-number">{{ user.free_messages }}</span>
                    <span class="stat-label">Free Messages</span>
                </div>
                <div class="stat-item">
                    <span class="stat-number">{{ likes_received|length }}</span>
                    <span class="stat-label">Likes</span>
                </div>
                <div class="stat-item">
                    <span class="stat-number">{{ unread_messages }}</span>
                    <span class="stat-label">Unread Messages</span>
                </div>
            </div>
            
            <a href="{{ url_for('discover') }}" class="btn">Start Discovering</a>
        </div>
        
        {% if premium_active %}
        <div class="premium-countdown">
            <h3>🎉 Premium Active</h3>
            <div class="countdown-number">{{ days_left }} days left</div>
            <p>Enjoy unlimited features!</p>
        </div>
        {% endif %}
        
        <div class="features">
            <a href="{{ url_for('discover') }}" class="feature-card">
                <div class="feature-icon">🔍</div>
                <h3>Discover</h3>
                <p>Find matches</p>
            </a>
            
            <a href="{{ url_for('chat') }}" class="feature-card">
                <div class="feature-icon">💬</div>
                <h3>Chat</h3>
                <p>Message matches</p>
                {% if unread_messages > 0 %}
                <span class="badge">{{ unread_messages }}</span>
                {% endif %}
            </a>
            
            <a href="{{ url_for('premium') }}" class="feature-card">
                <div class="feature-icon">⭐</div>
                <h3>Premium</h3>
                <p>Upgrade now</p>
            </a>
            
            <a href="{{ url_for('profile') }}" class="feature-card">
                <div class="feature-icon">👤</div>
                <h3>Profile</h3>
                <p>Edit profile</p>
            </a>
        </div>
        
        {% if likes_received %}
        <div class="likes-section">
            <h3 class="section-title">❤️ People Who Liked You</h3>
            {% for like in likes_received %}
            <div class="like-item">
                <div>
                    <strong>{{ like.liker_name }}</strong>
                    <div style="font-size: 0.8em; color: #666;">@{{ like.liker_username }}</div>
                </div>
                <button class="btn-like-back" onclick="likeBack({{ like.liker_id }})">Like Back</button>
            </div>
            {% endfor %}
        </div>
        {% endif %}
        
        {% if notifications %}
        <div class="notifications-section">
            <h3 class="section-title">🔔 Notifications</h3>
            {% for notification in notifications %}
            <div class="notification-item">
                <div>{{ notification.message }}</div>
                <small style="color: #666;">{{ notification.created_at }}</small>
            </div>
            {% endfor %}
        </div>
        {% endif %}
    </div>
    
    <div class="bottom-nav">
        <a href="{{ url_for('dashboard') }}" class="nav-item active">
            <div class="nav-icon">🏠</div>
            <div>Home</div>
        </a>
        <a href="{{ url_for('discover') }}" class="nav-item">
            <div class="nav-icon">🔍</div>
            <div>Discover</div>
        </a>
        <a href="{{ url_for('chat') }}" class="nav-item">
            <div class="nav-icon">💬</div>
            <div>Chat</div>
            {% if unread_messages > 0 %}
            <div class="badge">{{ unread_messages }}</div>
            {% endif %}
        </a>
        <a href="{{ url_for('premium') }}" class="nav-item">
            <div class="nav-icon">⭐</div>
            <div>Premium</div>
        </a>
        <a href="{{ url_for('profile') }}" class="nav-item">
            <div class="nav-icon">👤</div>
            <div>Profile</div>
        </a>
    </div>

    <script>
        function likeBack(userId) {
            fetch(`/like/${userId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('You liked them back! Check your matches.');
                        location.reload();
                    } else {
                        alert(data.error || 'Error liking back');
                    }
                });
        }
        
        let deferredPrompt;
        
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            deferredPrompt = e;
        });
        
        setTimeout(() => {
            if (deferredPrompt) {
                deferredPrompt.prompt();
                deferredPrompt.userChoice.then((choiceResult) => {
                    if (choiceResult.outcome === 'accepted') {
                        console.log('User accepted the install prompt');
                    }
                    deferredPrompt = null;
                });
            }
        }, 5000);
    </script>
</body>
</html>
'''

DISCOVER_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Discover - LoveConnect</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#ff4b7d">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f8f9fa;
            padding-bottom: 80px;
        }
        
        .header {
            background: linear-gradient(135deg, #ff4b7d, #ff6b6b);
            color: white;
            padding: 20px 15px;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        
        .nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .logo h1 {
            font-size: 1.4em;
            font-weight: 700;
        }
        
        .container {
            padding: 20px 15px;
        }
        
        .page-title {
            text-align: center;
            margin-bottom: 20px;
            color: #333;
            font-size: 1.5em;
        }
        
        .profiles {
            display: grid;
            gap: 15px;
        }
        
        .profile-card {
            background: white;
            border-radius: 20px;
            overflow: hidden;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        
        .profile-img {
            height: 200px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 3em;
        }
        
        .profile-info {
            padding: 20px;
        }
        
        .profile-name {
            font-size: 1.2em;
            font-weight: 600;
            margin-bottom: 5px;
        }
        
        .profile-details {
            color: #666;
            margin-bottom: 15px;
        }
        
        .profile-actions {
            display: flex;
            gap: 10px;
        }
        
        .btn {
            flex: 1;
            padding: 12px;
            border: none;
            border-radius: 10px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .btn-like {
            background: #ff4b7d;
            color: white;
        }
        
        .btn-swipe {
            background: #6c757d;
            color: white;
        }
        
        .btn:active {
            transform: scale(0.95);
        }
        
        .no-profiles {
            text-align: center;
            padding: 40px 20px;
            color: #666;
        }
        
        .bottom-nav {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: white;
            display: flex;
            justify-content: space-around;
            padding: 15px 0;
            box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
        }
        
        .nav-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            text-decoration: none;
            color: #666;
            font-size: 0.8em;
        }
        
        .nav-item.active {
            color: #ff4b7d;
        }
        
        .nav-icon {
            font-size: 1.2em;
            margin-bottom: 4px;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="nav">
            <div class="logo"><h1>💖 LoveConnect</h1></div>
        </div>
    </div>
    
    <div class="container">
        <h1 class="page-title">Discover Your Match</h1>
        
        {% if users %}
        <div class="profiles">
            {% for user in users %}
            <div class="profile-card" id="profile-{{ user.id }}">
                <div class="profile-img">👤</div>
                <div class="profile-info">
                    <div class="profile-name">{{ user.name }}</div>
                    <div class="profile-details">{{ user.age }} years • {{ user.gender }}</div>
                    <div class="profile-actions">
                        <button class="btn btn-like" onclick="likeUser({{ user.id }})">Like ❤️</button>
                        <button class="btn btn-swipe" onclick="swipeUser({{ user.id }})">Swipe 👉</button>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="no-profiles">
            <h2>No more profiles to discover!</h2>
            <p>Come back later to see new members.</p>
        </div>
        {% endif %}
    </div>
    
    <div class="bottom-nav">
        <a href="{{ url_for('dashboard') }}" class="nav-item">
            <div class="nav-icon">🏠</div>
            <div>Home</div>
        </a>
        <a href="{{ url_for('discover') }}" class="nav-item active">
            <div class="nav-icon">🔍</div>
            <div>Discover</div>
        </a>
        <a href="{{ url_for('chat') }}" class="nav-item">
            <div class="nav-icon">💬</div>
            <div>Chat</div>
        </a>
        <a href="{{ url_for('premium') }}" class="nav-item">
            <div class="nav-icon">⭐</div>
            <div>Premium</div>
        </a>
        <a href="{{ url_for('profile') }}" class="nav-item">
            <div class="nav-icon">👤</div>
            <div>Profile</div>
        </a>
    </div>

    <script>
        function likeUser(userId) {
            fetch(`/like/${userId}`)
                .then(response => {
                    if (response.ok) {
                        const profileCard = document.getElementById(`profile-${userId}`);
                        profileCard.style.transition = 'all 0.3s ease';
                        profileCard.style.opacity = '0';
                        profileCard.style.transform = 'translateX(-100px)';
                        
                        setTimeout(() => {
                            profileCard.remove();
                            if (document.querySelectorAll('.profile-card').length === 0) {
                                location.reload();
                            }
                        }, 300);
                    } else {
                        alert('Error liking user');
                    }
                });
        }
        
        function swipeUser(userId) {
            const profileCard = document.getElementById(`profile-${userId}`);
            profileCard.style.transition = 'all 0.3s ease';
            profileCard.style.opacity = '0';
            profileCard.style.transform = 'translateX(100px)';
            
            setTimeout(() => {
                profileCard.remove();
                if (document.querySelectorAll('.profile-card').length === 0) {
                    location.reload();
                }
            }, 300);
        }
    </script>
</body>
</html>
'''

CHAT_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chat - LoveConnect</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#ff4b7d">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f8f9fa;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        .header {
            background: linear-gradient(135deg, #ff4b7d, #ff6b6b);
            color: white;
            padding: 15px;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        
        .nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .logo h1 {
            font-size: 1.4em;
            font-weight: 700;
        }
        
        .container {
            display: flex;
            flex: 1;
            height: calc(100vh - 140px);
        }
        
        .matches-sidebar {
            width: 350px;
            background: white;
            border-right: 1px solid #e1e1e1;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }
        
        .chat-area {
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        
        .matches-header {
            padding: 20px;
            font-weight: 600;
            border-bottom: 1px solid #e1e1e1;
            background: #f8f9fa;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .back-to-home {
            background: #ff4b7d;
            color: white;
            border: none;
            padding: 8px 15px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.9em;
        }
        
        .match-item {
            padding: 15px 20px;
            border-bottom: 1px solid #f1f3f5;
            cursor: pointer;
            transition: background 0.3s ease;
            display: flex;
            align-items: center;
            gap: 12px;
            position: relative;
        }
        
        .match-item:hover, .match-item.active {
            background: #f8f9fa;
        }
        
        .user-avatar {
            width: 50px;
            height: 50px;
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea, #764ba2);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 1.2em;
            flex-shrink: 0;
        }
        
        .match-info {
            flex: 1;
            min-width: 0;
        }
        
        .match-name {
            font-weight: 600;
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .online-indicator {
            width: 8px;
            height: 8px;
            background: #28a745;
            border-radius: 50%;
            display: inline-block;
        }
        
        .last-message {
            font-size: 0.85em;
            color: #666;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        .message-time {
            font-size: 0.75em;
            color: #999;
            margin-top: 4px;
        }
        
        .unread-badge {
            background: #ff4b7d;
            color: white;
            border-radius: 50%;
            width: 20px;
            height: 20px;
            font-size: 0.7em;
            display: flex;
            align-items: center;
            justify-content: center;
            position: absolute;
            right: 15px;
            top: 50%;
            transform: translateY(-50%);
        }
        
        .chat-header {
            background: white;
            padding: 15px 20px;
            border-bottom: 1px solid #e1e1e1;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .chat-user {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .chat-status {
            font-size: 0.8em;
            color: #666;
        }
        
        .typing-indicator {
            font-size: 0.8em;
            color: #ff4b7d;
            font-style: italic;
        }
        
        .chat-messages {
            flex: 1;
            padding: 20px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 12px;
            background: #f8f9fa;
        }
        
        .message {
            max-width: 70%;
            padding: 12px 16px;
            border-radius: 18px;
            position: relative;
            animation: messageAppear 0.3s ease;
        }
        
        @keyframes messageAppear {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .message.sent {
            align-self: flex-end;
            background: #ff4b7d;
            color: white;
            border-bottom-right-radius: 4px;
        }
        
        .message.received {
            align-self: flex-start;
            background: white;
            color: #333;
            border: 1px solid #e1e1e1;
            border-bottom-left-radius: 4px;
        }
        
        .message-time {
            font-size: 0.7em;
            opacity: 0.7;
            margin-top: 5px;
            text-align: right;
        }
        
        .chat-input-container {
            background: white;
            padding: 15px 20px;
            border-top: 1px solid #e1e1e1;
            display: flex;
            gap: 10px;
            align-items: flex-end;
        }
        
        .chat-input {
            flex: 1;
            padding: 12px 16px;
            border: 1px solid #e1e1e1;
            border-radius: 25px;
            font-size: 16px;
            resize: none;
            max-height: 100px;
            outline: none;
        }
        
        .chat-input:focus {
            border-color: #ff4b7d;
        }
        
        .send-btn {
            background: #ff4b7d;
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 25px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.3s ease;
        }
        
        .send-btn:disabled {
            background: #ccc;
            cursor: not-allowed;
        }
        
        .no-chat {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #666;
            text-align: center;
            background: white;
        }
        
        .user-profile-modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }
        
        .profile-content {
            background: white;
            border-radius: 20px;
            padding: 30px;
            max-width: 400px;
            width: 90%;
            text-align: center;
        }
        
        .profile-avatar-large {
            width: 100px;
            height: 100px;
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea, #764ba2);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 2.5em;
            margin: 0 auto 20px;
        }
        
        .close-profile {
            background: #ff4b7d;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 10px;
            cursor: pointer;
            margin-top: 20px;
        }
        
        @media (max-width: 768px) {
            .matches-sidebar {
                width: 100%;
                display: none;
            }
            
            .matches-sidebar.active {
                display: flex;
            }
            
            .chat-area {
                display: none;
            }
            
            .chat-area.active {
                display: flex;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="nav">
            <div class="logo"><h1>💖 LoveConnect Chat</h1></div>
        </div>
    </div>
    
    <div class="container">
        <div class="matches-sidebar {% if not selected_user %}active{% endif %}" id="matchesSidebar">
            <div class="matches-header">
                <span>Your Matches ({{ matches|length }})</span>
                <button class="back-to-home" onclick="goToHome()">🏠 Home</button>
            </div>
            <div id="matchesList">
                {% for match in matches %}
                {% set unread_count = get_unread_message_count_with_user(session.user_id, match.id) %}
                <div class="match-item {% if selected_user == match.id|string %}active{% endif %}" 
                     onclick="selectMatch({{ match.id }})" id="match-{{ match.id }}">
                    <div class="user-avatar">👤</div>
                    <div class="match-info">
                        <div class="match-name">
                            {{ match.name }}
                            {% if match.is_online %}
                            <span class="online-indicator" title="Online"></span>
                            {% endif %}
                        </div>
                        <div class="last-message" id="last-message-{{ match.id }}">
                            {% if match.last_message %}
                                {{ match.last_message[:50] }}{% if match.last_message|length > 50 %}...{% endif %}
                            {% else %}
                                Start a conversation!
                            {% endif %}
                        </div>
                        {% if match.last_message_time %}
                        <div class="message-time" id="last-time-{{ match.id }}">
                            {{ match.last_message_time.strftime('%H:%M') if match.last_message_time else '' }}
                        </div>
                        {% endif %}
                    </div>
                    {% if unread_count > 0 %}
                    <div class="unread-badge" id="unread-{{ match.id }}">{{ unread_count }}</div>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
            {% if not matches %}
            <div style="padding: 40px 20px; text-align: center; color: #666;">
                <div style="font-size: 3em; margin-bottom: 10px;">💬</div>
                <h3>No matches yet</h3>
                <p>Start discovering to find your matches!</p>
            </div>
            {% endif %}
        </div>
        
        <div class="chat-area {% if selected_user %}active{% endif %}" id="chatArea">
            {% if selected_user %}
            {% set chat_user = get_user_by_id(selected_user|int) %}
            <div class="chat-header">
                <div class="chat-user" onclick="showUserProfile({{ chat_user.id }})" style="cursor: pointer;">
                    <div class="user-avatar">👤</div>
                    <div>
                        <div style="font-weight: 600;">{{ chat_user.name }}</div>
                        <div class="chat-status" id="chatStatus">
                            {% if chat_user.is_online %}
                            <span style="color: #28a745;">● Online</span>
                            {% else %}
                            <span>Last seen: {{ chat_user.last_seen.strftime('%Y-%m-%d %H:%M') if chat_user.last_seen else 'Unknown' }}</span>
                            {% endif %}
                        </div>
                    </div>
                </div>
                <div class="typing-indicator" id="typingIndicator" style="display: none;">
                    {{ chat_user.name }} is typing...
                </div>
                <div>
                    <button onclick="showMatches()" style="background: none; border: none; font-size: 1.2em; cursor: pointer; padding: 5px;">←</button>
                    <button class="back-to-home" onclick="goToHome()" style="margin-left: 10px;">🏠 Home</button>
                </div>
            </div>
            
            <div class="chat-messages" id="chatMessages">
                {% for message in messages %}
                <div class="message {% if message.sender_id == session.user_id %}sent{% else %}received{% endif %}" 
                     data-message-id="{{ message.id }}">
                    {{ message.message }}
                    <div class="message-time">{{ message.timestamp.strftime('%H:%M') if message.timestamp else '' }}</div>
                </div>
                {% endfor %}
            </div>
            
            <div class="chat-input-container">
                <textarea class="chat-input" id="messageInput" placeholder="Type your message..." 
                         rows="1" oninput="autoResize(this)" onkeydown="handleKeyDown(event)"></textarea>
                <button class="send-btn" id="sendBtn" onclick="sendMessage()">Send</button>
            </div>
            {% else %}
            <div class="no-chat">
                <div>
                    <div style="font-size: 4em; margin-bottom: 10px;">💬</div>
                    <h3>Select a match to start chatting</h3>
                    <p>Choose someone from your matches list to begin your conversation</p>
                    <button class="back-to-home" onclick="goToHome()" style="margin-top: 20px;">🏠 Back to Home</button>
                </div>
            </div>
            {% endif %}
        </div>
    </div>
    
    <!-- User Profile Modal -->
    <div class="user-profile-modal" id="userProfileModal">
        <div class="profile-content">
            <div class="profile-avatar-large">👤</div>
            <h2 id="profileName">{{ chat_user.name if selected_user else '' }}</h2>
            <div style="margin: 15px 0;">
                <p><strong>Age:</strong> <span id="profileAge">{{ chat_user.age if selected_user else '' }}</span></p>
                <p><strong>Gender:</strong> <span id="profileGender">{{ chat_user.gender if selected_user else '' }}</span></p>
                <p><strong>Username:</strong> @<span id="profileUsername">{{ chat_user.username if selected_user else '' }}</span></p>
                <p><strong>Status:</strong> <span id="profileStatus">{% if selected_user %}{% if chat_user.is_online %}Online{% else %}Offline{% endif %}{% endif %}</span></p>
            </div>
            <button class="close-profile" onclick="closeUserProfile()">Close</button>
        </div>
    </div>

    <script>
        const socket = io();
        let selectedUserId = {{ selected_user|default('null') }};
        let typingTimer;
        
        function goToHome() {
            window.location.href = "{{ url_for('dashboard') }}";
        }
        
        // Socket event handlers
        socket.on('connect', function() {
            console.log('Connected to server');
        });
        
        socket.on('receive_message', function(data) {
            if (data.sender_id == selectedUserId) {
                addMessageToChat(data, 'received');
                markMessagesAsRead();
            }
            updateMatchList();
        });
        
        socket.on('message_sent', function(data) {
            if (data.receiver_id == selectedUserId) {
                addMessageToChat(data, 'sent');
            }
            updateMatchList();
        });
        
        socket.on('user_online', function(data) {
            if (data.user_id == selectedUserId) {
                updateChatStatus('online');
            }
            updateMatchOnlineStatus(data.user_id, true);
        });
        
        socket.on('user_offline', function(data) {
            if (data.user_id == selectedUserId) {
                updateChatStatus('offline');
            }
            updateMatchOnlineStatus(data.user_id, false);
        });
        
        socket.on('user_typing', function(data) {
            if (data.user_id == selectedUserId) {
                showTypingIndicator();
            }
        });
        
        socket.on('user_stop_typing', function(data) {
            if (data.user_id == selectedUserId) {
                hideTypingIndicator();
            }
        });
        
        socket.on('messages_read', function(data) {
            // Messages were read by the other user
            console.log('Messages read by user:', data.user_id);
        });
        
        socket.on('update_match_list', function(data) {
            updateMatchList();
        });
        
        function selectMatch(userId) {
            window.location.href = `{{ url_for('chat') }}?user_id=${userId}`;
        }
        
        function showMatches() {
            window.location.href = '{{ url_for("chat") }}';
        }
        
        function autoResize(textarea) {
            textarea.style.height = 'auto';
            textarea.style.height = Math.min(textarea.scrollHeight, 100) + 'px';
        }
        
        function handleKeyDown(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendMessage();
            } else {
                // Typing indicators
                clearTimeout(typingTimer);
                socket.emit('typing_start', {receiver_id: selectedUserId});
                
                typingTimer = setTimeout(() => {
                    socket.emit('typing_stop', {receiver_id: selectedUserId});
                }, 1000);
            }
        }
        
        function sendMessage() {
            const input = document.getElementById('messageInput');
            const message = input.value.trim();
            
            if (message && selectedUserId) {
                socket.emit('send_message', {
                    receiver_id: selectedUserId,
                    message: message
                });
                
                input.value = '';
                autoResize(input);
                
                // Stop typing indicator
                socket.emit('typing_stop', {receiver_id: selectedUserId});
                clearTimeout(typingTimer);
            }
        }
        
        function addMessageToChat(messageData, type) {
            const chatMessages = document.getElementById('chatMessages');
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${type}`;
            messageDiv.innerHTML = `
                ${messageData.message}
                <div class="message-time">${messageData.timestamp}</div>
            `;
            
            chatMessages.appendChild(messageDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
        
        function updateChatStatus(status) {
            const statusElement = document.getElementById('chatStatus');
            if (status === 'online') {
                statusElement.innerHTML = '<span style="color: #28a745;">● Online</span>';
            } else {
                statusElement.innerHTML = '<span>Last seen: Just now</span>';
            }
        }
        
        function updateMatchOnlineStatus(userId, isOnline) {
            const matchItem = document.getElementById(`match-${userId}`);
            if (matchItem) {
                const onlineIndicator = matchItem.querySelector('.online-indicator');
                if (onlineIndicator) {
                    onlineIndicator.style.display = isOnline ? 'inline-block' : 'none';
                }
            }
        }
        
        function showTypingIndicator() {
            const indicator = document.getElementById('typingIndicator');
            indicator.style.display = 'block';
        }
        
        function hideTypingIndicator() {
            const indicator = document.getElementById('typingIndicator');
            indicator.style.display = 'none';
        }
        
        function markMessagesAsRead() {
            if (selectedUserId) {
                socket.emit('mark_messages_read', {other_user_id: selectedUserId});
                // Update unread badge
                const unreadBadge = document.getElementById(`unread-${selectedUserId}`);
                if (unreadBadge) {
                    unreadBadge.style.display = 'none';
                }
            }
        }
        
        function updateMatchList() {
            // Refresh the matches list via AJAX
            fetch('/get_matches_data')
                .then(response => response.json())
                .then(matches => {
                    const matchesList = document.getElementById('matchesList');
                    matchesList.innerHTML = '';
                    
                    matches.forEach(match => {
                        const unreadCount = match.unread_count || 0;
                        const matchItem = document.createElement('div');
                        matchItem.className = `match-item ${selectedUserId == match.id ? 'active' : ''}`;
                        matchItem.id = `match-${match.id}`;
                        matchItem.onclick = () => selectMatch(match.id);
                        
                        matchItem.innerHTML = `
                            <div class="user-avatar">👤</div>
                            <div class="match-info">
                                <div class="match-name">
                                    ${match.name}
                                    ${match.is_online ? '<span class="online-indicator" title="Online"></span>' : ''}
                                </div>
                                <div class="last-message" id="last-message-${match.id}">
                                    ${match.last_message ? (match.last_message.length > 50 ? match.last_message.substring(0, 50) + '...' : match.last_message) : 'Start a conversation!'}
                                </div>
                                ${match.last_message_time ? `<div class="message-time" id="last-time-${match.id}">${match.last_message_time}</div>` : ''}
                            </div>
                            ${unreadCount > 0 ? `<div class="unread-badge" id="unread-${match.id}">${unreadCount}</div>` : ''}
                        `;
                        
                        matchesList.appendChild(matchItem);
                    });
                });
        }
        
        function showUserProfile(userId) {
            document.getElementById('userProfileModal').style.display = 'flex';
        }
        
        function closeUserProfile() {
            document.getElementById('userProfileModal').style.display = 'none';
        }
        
        // Initialize chat
        document.addEventListener('DOMContentLoaded', function() {
            const chatMessages = document.getElementById('chatMessages');
            if (chatMessages) {
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
            
            // Mark messages as read when chat is opened
            if (selectedUserId) {
                markMessagesAsRead();
            }
            
            // Auto-refresh matches every 10 seconds
            setInterval(updateMatchList, 10000);
        });
        
        // Mobile responsive behavior
        function checkScreenSize() {
            const matchesSidebar = document.getElementById('matchesSidebar');
            const chatArea = document.getElementById('chatArea');
            
            if (window.innerWidth <= 768) {
                if (selectedUserId) {
                    matchesSidebar.classList.remove('active');
                    chatArea.classList.add('active');
                } else {
                    matchesSidebar.classList.add('active');
                    chatArea.classList.remove('active');
                }
            }
        }
        
        window.addEventListener('resize', checkScreenSize);
        checkScreenSize();
    </script>
</body>
</html>
'''

PREMIUM_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Premium - LoveConnect</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#ff4b7d">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f8f9fa;
            padding-bottom: 80px;
        }
        
        .header {
            background: linear-gradient(135deg, #ff4b7d, #ff6b6b);
            color: white;
            padding: 20px 15px;
        }
        
        .nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .logo h1 {
            font-size: 1.4em;
            font-weight: 700;
        }
        
        .container {
            padding: 20px 15px;
        }
        
        .premium-card {
            background: white;
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            text-align: center;
        }
        
        .premium-title {
            color: #ff4b7d;
            font-size: 1.8em;
            margin-bottom: 10px;
        }
        
        .premium-price {
            font-size: 3em;
            font-weight: 700;
            color: #333;
            margin-bottom: 20px;
        }
        
        .premium-features {
            list-style: none;
            margin: 25px 0;
            text-align: left;
        }
        
        .premium-features li {
            padding: 12px 0;
            border-bottom: 1px solid #f1f3f5;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .premium-features li:before {
            content: "✓";
            color: #28a745;
            font-weight: bold;
            font-size: 1.2em;
        }
        
        .btn {
            background: linear-gradient(135deg, #ff4b7d, #ff6b6b);
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 25px;
            font-size: 1.1em;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            transition: all 0.3s ease;
        }
        
        .btn:active {
            transform: scale(0.95);
        }
        
        .active-premium {
            background: linear-gradient(135deg, #ffd700, #ffa500);
            color: white;
            border-radius: 20px;
            padding: 25px;
            margin-bottom: 20px;
            text-align: center;
        }
        
        .countdown-number {
            font-size: 2.5em;
            font-weight: 700;
            margin: 10px 0;
        }
        
        .payment-section {
            background: white;
            border-radius: 20px;
            padding: 25px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        
        .payment-title {
            font-size: 1.3em;
            margin-bottom: 20px;
            text-align: center;
            color: #333;
        }
        
        .qr-code {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            margin-bottom: 20px;
        }
        
        .qr-code img {
            max-width: 200px;
            height: auto;
            margin: 0 auto;
            display: block;
        }
        
        .payment-info {
            background: #e7f3ff;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        
        .payment-info p {
            margin: 5px 0;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 600;
        }
        
        .form-group input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e1e1e1;
            border-radius: 10px;
            font-size: 16px;
        }
        
        .bottom-nav {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: white;
            display: flex;
            justify-content: space-around;
            padding: 15px 0;
            box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
        }
        
        .nav-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            text-decoration: none;
            color: #666;
            font-size: 0.8em;
        }
        
        .nav-item.active {
            color: #ff4b7d;
        }
        
        .nav-icon {
            font-size: 1.2em;
            margin-bottom: 4px;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="nav">
            <div class="logo"><h1>💖 LoveConnect</h1></div>
        </div>
    </div>
    
    <div class="container">
        {% if premium_active %}
        <div class="active-premium">
            <h2 class="premium-title">Premium Active! 🎉</h2>
            <div class="countdown-number">{{ days_left }} days left</div>
            <p>Enjoy unlimited messages, video calls, and premium features!</p>
        </div>
        {% endif %}
        
        <div class="premium-card">
            <h2 class="premium-title">LoveConnect Premium</h2>
            <div class="premium-price">₹9<span style="font-size: 0.5em; color: #666;">/month</span></div>
            
            <ul class="premium-features">
                <li>Unlimited Messages</li>
                <li>Unlimited Likes</li>
                <li>Video Calls</li>
                <li>Priority Customer Support</li>
                <li>See Who Liked You</li>
                <li>Advanced Search Filters</li>
                <li>No Ads</li>
                <li>Profile Boosts</li>
            </ul>
            
            {% if not premium_active %}
            <a href="#payment" class="btn">Get Premium Now</a>
            {% endif %}
        </div>
        
        {% if not premium_active %}
        <div class="payment-section" id="payment">
            <h3 class="payment-title">Complete Your Payment</h3>
            
            <div class="qr-code">
                <img src="data:image/png;base64,{{ qr_code_img }}" alt="QR Code for UPI Payment">
                <p style="margin-top: 15px; font-weight: 600;">Scan this QR code with any UPI app</p>
            </div>
            
            <div class="payment-info">
                <p><strong>UPI ID:</strong> 7678500304@axl</p>
                <p><strong>Amount:</strong> ₹9</p>
                <p><strong>Note:</strong> LoveConnect Premium</p>
            </div>
            
            <form method="POST" action="{{ url_for('verify_payment') }}">
                <div class="form-group">
                    <label for="txn_id">Transaction ID (UPI Reference Number)</label>
                    <input type="text" id="txn_id" name="txn_id" required 
                           placeholder="Enter UPI transaction reference number">
                </div>
                <button type="submit" class="btn" style="width: 100%;">Submit Payment Verification</button>
            </form>
            
            <p style="text-align: center; margin-top: 15px; color: #666; font-size: 0.9em;">
                After payment, enter the transaction reference number.<br>
                Our team will verify your payment within 24 hours.
            </p>
        </div>
        {% endif %}
    </div>
    
    <div class="bottom-nav">
        <a href="{{ url_for('dashboard') }}" class="nav-item">
            <div class="nav-icon">🏠</div>
            <div>Home</div>
        </a>
        <a href="{{ url_for('discover') }}" class="nav-item">
            <div class="nav-icon">🔍</div>
            <div>Discover</div>
        </a>
        <a href="{{ url_for('chat') }}" class="nav-item">
            <div class="nav-icon">💬</div>
            <div>Chat</div>
        </a>
        <a href="{{ url_for('premium') }}" class="nav-item active">
            <div class="nav-icon">⭐</div>
            <div>Premium</div>
        </a>
        <a href="{{ url_for('profile') }}" class="nav-item">
            <div class="nav-icon">👤</div>
            <div>Profile</div>
        </a>
    </div>
</body>
</html>
'''

PROFILE_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Profile - LoveConnect</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#ff4b7d">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f8f9fa;
            padding-bottom: 80px;
        }
        
        .header {
            background: linear-gradient(135deg, #ff4b7d, #ff6b6b);
            color: white;
            padding: 20px 15px;
        }
        
        .nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .logo h1 {
            font-size: 1.4em;
            font-weight: 700;
        }
        
        .container {
            padding: 20px 15px;
        }
        
        .profile-card {
            background: white;
            border-radius: 20px;
            padding: 25px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            max-width: 500px;
            margin: 0 auto;
        }
        
        .profile-header {
            text-align: center;
            margin-bottom: 25px;
        }
        
        .profile-avatar {
            width: 100px;
            height: 100px;
            border-radius: 50%;
            background: #f8f9fa;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 15px;
            overflow: hidden;
            border: 3px solid #ff4b7d;
        }
        
        .profile-avatar img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        
        .profile-name {
            font-size: 1.4em;
            font-weight: 600;
            margin-bottom: 5px;
        }
        
        .premium-badge {
            background: linear-gradient(135deg, #ffd700, #ffa500);
            color: white;
            padding: 5px 12px;
            border-radius: 15px;
            font-size: 0.8em;
            margin-left: 8px;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        label {
            display: block;
            margin-bottom: 6px;
            color: #333;
            font-weight: 600;
            font-size: 14px;
        }
        
        input, select {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e1e1e1;
            border-radius: 10px;
            font-size: 16px;
            transition: all 0.3s ease;
        }
        
        input:focus, select:focus {
            border-color: #ff4b7d;
            outline: none;
        }
        
        .btn {
            background: linear-gradient(135deg, #ff4b7d, #ff6b6b);
            color: white;
            border: none;
            padding: 15px;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            transition: all 0.3s ease;
            margin-top: 10px;
        }
        
        .btn:active {
            transform: scale(0.98);
        }
        
        .row {
            display: flex;
            gap: 10px;
        }
        
        .row .form-group {
            flex: 1;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-top: 25px;
            padding-top: 20px;
            border-top: 1px solid #f1f3f5;
        }
        
        .stat-item {
            text-align: center;
            padding: 15px 5px;
        }
        
        .stat-number {
            font-size: 1.2em;
            font-weight: 700;
            color: #ff4b7d;
            display: block;
        }
        
        .stat-label {
            font-size: 0.8em;
            color: #666;
            margin-top: 5px;
        }
        
        .success-message {
            background: #d4edda;
            color: #155724;
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 15px;
            text-align: center;
            border: 1px solid #c3e6cb;
        }
        
        .bottom-nav {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: white;
            display: flex;
            justify-content: space-around;
            padding: 15px 0;
            box-shadow: 0 -2px 10px rgba(0,0,0,0.1);
        }
        
        .nav-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            text-decoration: none;
            color: #666;
            font-size: 0.8em;
            position: relative;
        }
        
        .nav-item.active {
            color: #ff4b7d;
        }
        
        .nav-icon {
            font-size: 1.2em;
            margin-bottom: 4px;
        }
        
        .badge {
            position: absolute;
            top: -5px;
            right: -5px;
            background: #ff4b7d;
            color: white;
            border-radius: 50%;
            width: 18px;
            height: 18px;
            font-size: 0.7em;
            display: flex;
            align-items: center;
            justify-content: center;
        }
    </style>
    <script>
        function previewImage(event) {
            const input = event.target;
            const preview = document.getElementById('profile-preview');
            
            if (input.files && input.files[0]) {
                const reader = new FileReader();
                
                reader.onload = function(e) {
                    preview.innerHTML = '<img src="' + e.target.result + '" alt="Profile Preview">';
                }
                
                reader.readAsDataURL(input.files[0]);
            }
        }
        
        function validateForm() {
            const age = document.getElementById('age').value;
            const mobile = document.getElementById('mobile').value;
            
            if (age < 18 || age > 100) {
                alert('Age must be between 18 and 100');
                return false;
            }
            
            if (!/^[0-9]{10}$/.test(mobile)) {
                alert('Please enter a valid 10-digit mobile number');
                return false;
            }
            
            return true;
        }
    </script>
</head>
<body>
    <div class="header">
        <div class="nav">
            <div class="logo"><h1>💖 LoveConnect</h1></div>
        </div>
    </div>
    
    <div class="container">
        <div class="profile-card">
            {% if request.args.get('success') %}
            <div class="success-message">
                Profile updated successfully!
            </div>
            {% endif %}
            
            <div class="profile-header">
                <div class="profile-avatar" id="profile-preview">
                    {% if profile_image %}
                    <img src="data:image/jpeg;base64,{{ profile_image }}" alt="Profile Image">
                    {% else %}
                    <div style="font-size: 2.5em;">👤</div>
                    {% endif %}
                </div>
                <div class="profile-name">
                    {{ user.name }}
                    {% if premium_active %}<span class="premium-badge">PREMIUM</span>{% endif %}
                </div>
                <div style="color: #666;">@{{ user.username }}</div>
            </div>
            
            <form method="POST" enctype="multipart/form-data" onsubmit="return validateForm()">
                <div class="form-group">
                    <label for="image">Update Profile Image</label>
                    <input type="file" id="image" name="image" accept="image/*" onchange="previewImage(event)">
                    <small style="color: #666; font-size: 0.8em;">Max 5MB - JPG, PNG, GIF</small>
                </div>
                
                <div class="form-group">
                    <label for="name">Full Name</label>
                    <input type="text" id="name" name="name" value="{{ user.name }}" required>
                </div>
                
                <div class="row">
                    <div class="form-group">
                        <label for="mobile">Mobile Number</label>
                        <input type="tel" id="mobile" name="mobile" value="{{ user.mobile }}" required 
                               pattern="[0-9]{10}" title="10-digit mobile number">
                    </div>
                    <div class="form-group">
                        <label for="age">Age</label>
                        <input type="number" id="age" name="age" value="{{ user.age }}" min="18" max="100" required>
                    </div>
                </div>
                
                <div class="form-group">
                    <label for="gender">Gender</label>
                    <select id="gender" name="gender" required>
                        <option value="Male" {% if user.gender == 'Male' %}selected{% endif %}>Male</option>
                        <option value="Female" {% if user.gender == 'Female' %}selected{% endif %}>Female</option>
                        <option value="Other" {% if user.gender == 'Other' %}selected{% endif %}>Other</option>
                    </select>
                </div>
                
                <div class="form-group">
                    <label for="username">Username</label>
                    <input type="text" id="username" value="{{ user.username }}" disabled>
                    <small style="color: #666; font-size: 0.8em;">Username cannot be changed</small>
                </div>
                
                <button type="submit" class="btn">Update Profile</button>
            </form>
            
            <div class="stats">
                <div class="stat-item">
                    <span class="stat-number">{{ user.free_messages }}</span>
                    <span class="stat-label">Free Messages</span>
                </div>
                <div class="stat-item">
                    <span class="stat-number">{{ unread_messages }}</span>
                    <span class="stat-label">Unread Messages</span>
                </div>
                <div class="stat-item">
                    <span class="stat-number">{% if premium_active %}Yes{% else %}No{% endif %}</span>
                    <span class="stat-label">Premium</span>
                </div>
            </div>
        </div>
    </div>
    
    <div class="bottom-nav">
        <a href="{{ url_for('dashboard') }}" class="nav-item">
            <div class="nav-icon">🏠</div>
            <div>Home</div>
        </a>
        <a href="{{ url_for('discover') }}" class="nav-item">
            <div class="nav-icon">🔍</div>
            <div>Discover</div>
        </a>
        <a href="{{ url_for('chat') }}" class="nav-item">
            <div class="nav-icon">💬</div>
            <div>Chat</div>
            {% if unread_messages > 0 %}
            <div class="badge">{{ unread_messages }}</div>
            {% endif %}
        </a>
        <a href="{{ url_for('premium') }}" class="nav-item">
            <div class="nav-icon">⭐</div>
            <div>Premium</div>
        </a>
        <a href="{{ url_for('profile') }}" class="nav-item active">
            <div class="nav-icon">👤</div>
            <div>Profile</div>
        </a>
    </div>
</body>
</html>
'''

ADMIN_DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin - LoveConnect</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f8f9fa;
            padding: 20px;
        }
        
        .header {
            background: linear-gradient(135deg, #ff4b7d, #ff6b6b);
            color: white;
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 20px;
        }
        
        .nav {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .logo h1 {
            font-size: 1.5em;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }
        
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 15px;
            text-align: center;
            box-shadow: 0 3px 10px rgba(0,0,0,0.1);
        }
        
        .stat-number {
            font-size: 2em;
            font-weight: 700;
            color: #ff4b7d;
        }
        
        .admin-section {
            background: white;
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 3px 10px rgba(0,0,0,0.1);
        }
        
        .section-title {
            font-size: 1.3em;
            margin-bottom: 20px;
            color: #333;
            border-bottom: 2px solid #f1f3f5;
            padding-bottom: 10px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th, td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #f1f3f5;
        }
        
        th {
            background: #f8f9fa;
            font-weight: 600;
            color: #333;
        }
        
        .btn {
            padding: 8px 15px;
            border: none;
            border-radius: 8px;
            font-size: 0.9em;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }
        
        .btn-verify {
            background: #28a745;
            color: white;
        }
        
        .btn-block {
            background: #dc3545;
            color: white;
        }
        
        .btn-unblock {
            background: #ffc107;
            color: #212529;
        }
        
        .search-bar {
            margin-bottom: 20px;
            display: flex;
            gap: 10px;
        }
        
        .search-bar input {
            flex: 1;
            padding: 12px 15px;
            border: 2px solid #e1e1e1;
            border-radius: 10px;
        }
        
        .search-bar button {
            background: #ff4b7d;
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 10px;
            cursor: pointer;
        }
        
        .premium-active {
            background: #28a745;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8em;
        }
        
        .premium-inactive {
            background: #6c757d;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8em;
        }
        
        .payment-status {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8em;
        }
        
        .payment-verified {
            background: #28a745;
            color: white;
        }
        
        .payment-pending {
            background: #ffc107;
            color: #212529;
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="nav">
            <div class="logo"><h1>💖 LoveConnect - Admin Panel</h1></div>
            <a href="{{ url_for('logout') }}" style="color: white; text-decoration: none;">Logout</a>
        </div>
    </div>
    
    <div class="stats">
        <div class="stat-card">
            <div class="stat-number">{{ users|length }}</div>
            <div>Total Users</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{{ pending_payments|length }}</div>
            <div>Pending Payments</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{{ users|selectattr('is_premium')|list|length }}</div>
            <div>Premium Users</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{{ users|selectattr('is_blocked')|list|length }}</div>
            <div>Blocked Users</div>
        </div>
    </div>
    
    <div class="admin-section">
        <h2 class="section-title">User Management</h2>
        
        <form method="GET" class="search-bar">
            <input type="text" name="search" placeholder="Search users..." value="{{ search_term }}">
            <button type="submit">Search</button>
            {% if search_term %}
            <a href="{{ url_for('admin_dashboard') }}" class="btn" style="background: #6c757d; color: white;">Clear</a>
            {% endif %}
        </form>
        
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>Username</th>
                    <th>Mobile</th>
                    <th>Age</th>
                    <th>Gender</th>
                    <th>Premium</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {% for user in users %}
                <tr>
                    <td>{{ user.id }}</td>
                    <td>{{ user.name }}</td>
                    <td>@{{ user.username }}</td>
                    <td>{{ user.mobile }}</td>
                    <td>{{ user.age }}</td>
                    <td>{{ user.gender }}</td>
                    <td>
                        {% if user.is_premium %}
                        <span class="premium-active">Active</span>
                        {% else %}
                        <span class="premium-inactive">Inactive</span>
                        {% endif %}
                    </td>
                    <td>
                        {% if user.is_blocked %}
                        <span style="color: #dc3545;">Blocked</span>
                        {% elif user.is_verified %}
                        <span style="color: #28a745;">Verified</span>
                        {% else %}
                        <span style="color: #ffc107;">Pending</span>
                        {% endif %}
                    </td>
                    <td>
                        {% if not user.is_verified %}
                        <a href="{{ url_for('admin_verify_user', user_id=user.id) }}" class="btn btn-verify">Verify</a>
                        {% endif %}
                        {% if user.is_blocked %}
                        <a href="{{ url_for('admin_unblock_user', user_id=user.id) }}" class="btn btn-unblock">Unblock</a>
                        {% else %}
                        <a href="{{ url_for('admin_block_user', user_id=user.id) }}" class="btn btn-block">Block</a>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    
    <div class="admin-section">
        <h2 class="section-title">Payment Management</h2>
        
        <form method="GET" class="search-bar">
            <input type="text" name="payment_search" placeholder="Search payments..." value="{{ payment_search }}">
            <button type="submit">Search</button>
            {% if payment_search %}
            <a href="{{ url_for('admin_dashboard') }}" class="btn" style="background: #6c757d; color: white;">Clear</a>
            {% endif %}
        </form>
        
        <table>
            <thead>
                <tr>
                    <th>Payment ID</th>
                    <th>User</th>
                    <th>Transaction ID</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Date</th>
                    <th>User Premium</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                {% for payment in all_payments %}
                <tr>
                    <td>{{ payment.id }}</td>
                    <td>{{ payment.user_name }} (@{{ payment.username }})</td>
                    <td>{{ payment.txn_id }}</td>
                    <td>₹{{ payment.amount }}</td>
                    <td>
                        <span class="payment-status {% if payment.status == 'verified' %}payment-verified{% else %}payment-pending{% endif %}">
                            {{ payment.status }}
                        </span>
                    </td>
                    <td>{{ payment.created_at.strftime('%Y-%m-%d %H:%M') if payment.created_at else 'N/A' }}</td>
                    <td>
                        {% if payment.is_premium %}
                        <span class="premium-active">Active</span>
                        {% if payment.premium_expiry %}
                        <br><small>Expires: {{ payment.premium_expiry.strftime('%Y-%m-%d') if payment.premium_expiry else 'N/A' }}</small>
                        {% endif %}
                        {% else %}
                        <span class="premium-inactive">Inactive</span>
                        {% endif %}
                    </td>
                    <td>
                        {% if payment.status == 'pending' %}
                        <a href="{{ url_for('admin_verify_payment', payment_id=payment.id) }}" class="btn btn-verify">Verify</a>
                        {% else %}
                        <span style="color: #28a745;">Verified</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
                {% if not all_payments %}
                <tr>
                    <td colspan="8" style="text-align: center; padding: 20px; color: #666;">
                        No payments found
                    </td>
                </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
    
    <div class="admin-section">
        <h2 class="section-title">Payment Verification</h2>
        
        <table>
            <thead>
                <tr>
                    <th>Payment ID</th>
                    <th>User</th>
                    <th>Transaction ID</th>
                    <th>Amount</th>
                    <th>Status</th>
                    <th>Date</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                {% for payment in pending_payments %}
                <tr>
                    <td>{{ payment.id }}</td>
                    <td>{{ payment.user_name }}</td>
                    <td>{{ payment.txn_id }}</td>
                    <td>₹{{ payment.amount }}</td>
                    <td style="color: #ffc107;">{{ payment.status }}</td>
                    <td>{{ payment.created_at.strftime('%Y-%m-%d %H:%M') if payment.created_at else 'N/A' }}</td>
                    <td>
                        <a href="{{ url_for('admin_verify_payment', payment_id=payment.id) }}" class="btn btn-verify">Verify</a>
                    </td>
                </tr>
                {% endfor %}
                {% if not pending_payments %}
                <tr>
                    <td colspan="7" style="text-align: center; padding: 20px; color: #666;">
                        No pending payments to verify
                    </td>
                </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
</body>
</html>
'''

# PWA Routes
@app.route('/manifest.json')
def manifest():
    manifest_data = {
        "name": "LoveConnect",
        "short_name": "LoveConnect",
        "description": "Find your perfect match",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#ff4b7d",
        "orientation": "portrait",
        "icons": [
            {
                "src": "/static/icon-192.png",
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": "/static/icon-512.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ],
        "categories": ["social", "dating"]
    }
    return jsonify(manifest_data)

@app.route('/sw.js')
def service_worker():
    service_worker_js = '''
    const CACHE_NAME = 'loveconnect-v1';
    const urlsToCache = ['/', '/static/icon-192.png', '/static/icon-512.png'];

    self.addEventListener('install', event => {
      event.waitUntil(
        caches.open(CACHE_NAME)
          .then(cache => cache.addAll(urlsToCache))
      );
    });

    self.addEventListener('fetch', event => {
      event.respondWith(
        caches.match(event.request)
          .then(response => {
            if (response) {
              return response;
            }
            return fetch(event.request);
          })
      );
    });
    '''
    return app.response_class(service_worker_js, mimetype='application/javascript')

# Static files route for PWA icons
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_file(f'static/{filename}')

# New API route for real-time match data
@app.route('/get_matches_data')
def get_matches_data():
    if 'user_id' not in session or session.get('is_admin'):
        return jsonify([])
    
    matches = get_matches(session['user_id'])
    
    # Add unread count to each match
    for match in matches:
        match['unread_count'] = get_unread_message_count_with_user(session['user_id'], match['id'])
        if match['last_message_time'] and isinstance(match['last_message_time'], datetime):
            match['last_message_time'] = match['last_message_time'].strftime('%H:%M')
    
    return jsonify(matches)

# Main Routes
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_type = request.form.get('user_type', 'user')
        
        if user_type == 'admin' and username == 'admin' and password == 'admin123':
            session['user_id'] = 0
            session['username'] = 'admin'
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        
        user = get_user_by_username(username)
        if user and user['password'] == password:
            if user['is_blocked']:
                return render_template_string(LOGIN_HTML, error="Your account has been blocked. Please contact support.")
            
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = False
            session['premium_active'] = is_premium_active(user['id'])
            
            # Update online status
            update_user_online_status(user['id'], True)
            
            return redirect(url_for('dashboard'))
        else:
            return render_template_string(LOGIN_HTML, error="Invalid username or password")
    
    return render_template_string(LOGIN_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        mobile = request.form['mobile']
        age = request.form['age']
        gender = request.form['gender']
        username = request.form['username']
        password = request.form['password']
        
        image = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                image = file.read()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if image:
                cursor.execute("INSERT INTO users (name, mobile, age, gender, username, password, image) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                              (name, mobile, age, gender, username, password, image))
            else:
                cursor.execute("INSERT INTO users (name, mobile, age, gender, username, password) VALUES (%s, %s, %s, %s, %s, %s)",
                              (name, mobile, age, gender, username, password))
            
            conn.commit()
            cursor.close()
            conn.close()
            return redirect(url_for('login'))
        except mysql.connector.IntegrityError:
            cursor.close()
            conn.close()
            return render_template_string(REGISTER_HTML, error="Username already exists")
        except Exception as e:
            cursor.close()
            conn.close()
            return render_template_string(REGISTER_HTML, error="An error occurred during registration")
    
    return render_template_string(REGISTER_HTML)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    user = get_user_by_id(session['user_id'])
    premium_active = is_premium_active(session['user_id'])
    notifications = get_notifications(session['user_id'])
    unread_count = get_unread_notifications_count(session['user_id'])
    likes_received = get_likes_received(session['user_id'])
    unread_messages = get_unread_message_count(session['user_id'])
    
    days_left = 0
    if premium_active:
        days_left = get_premium_days_left(session['user_id'])
    
    return render_template_string(DASHBOARD_HTML, user=user, premium_active=premium_active, 
                                notifications=notifications, unread_count=unread_count, 
                                likes_received=likes_received, days_left=days_left,
                                unread_messages=unread_messages)

@app.route('/discover')
def discover():
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    users = get_all_users()
    return render_template_string(DISCOVER_HTML, users=users)

@app.route('/like/<int:user_id>')
def like_user(user_id):
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    user = get_user_by_id(session['user_id'])
    premium_active = is_premium_active(session['user_id'])
    
    if not premium_active and user['free_messages'] <= 0:
        return jsonify({'success': False, 'error': 'No free likes left. Please upgrade to premium.'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM likes WHERE liker_id = %s AND liked_id = %s", (session['user_id'], user_id))
    existing_like = cursor.fetchone()
    
    if not existing_like:
        cursor.execute("INSERT INTO likes (liker_id, liked_id, status) VALUES (%s, %s, %s)", 
                      (session['user_id'], user_id, 'liked'))
        
        liked_user = get_user_by_id(user_id)
        current_user = get_user_by_id(session['user_id'])
        add_notification(user_id, f"{current_user['name']} liked your profile!")
        
        cursor.execute("SELECT * FROM likes WHERE liker_id = %s AND liked_id = %s", (user_id, session['user_id']))
        mutual_like = cursor.fetchone()
        
        if mutual_like:
            cursor.execute("INSERT INTO matches (user1_id, user2_id, status) VALUES (%s, %s, %s)", 
                          (session['user_id'], user_id, 'matched'))
            
            add_notification(session['user_id'], f"You matched with {liked_user['name']}! Start chatting now.")
            add_notification(user_id, f"You matched with {current_user['name']}! Start chatting now.")
        
        if not premium_active:
            cursor.execute("UPDATE users SET free_messages = free_messages - 1 WHERE id = %s", (session['user_id'],))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/swipe/<int:user_id>')
def swipe_user(user_id):
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("INSERT INTO likes (liker_id, liked_id, status) VALUES (%s, %s, %s)", 
                  (session['user_id'], user_id, 'swiped'))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/chat')
def chat():
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    matches = get_matches(session['user_id'])
    selected_user = request.args.get('user_id')
    messages = []
    
    if selected_user:
        messages = get_messages(session['user_id'], int(selected_user))
        # Mark messages as read when opening chat
        mark_messages_as_read(session['user_id'], int(selected_user))
    
    user = get_user_by_id(session['user_id'])
    premium_active = is_premium_active(session['user_id'])
    
    return render_template_string(CHAT_HTML, matches=matches, selected_user=selected_user, 
                                messages=messages, user=user, premium_active=premium_active, 
                                get_user_by_id=get_user_by_id, get_last_message=get_last_message,
                                get_unread_message_count_with_user=get_unread_message_count_with_user)

@app.route('/send_message', methods=['POST'])
def send_message():
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    receiver_id = request.form['receiver_id']
    message = request.form['message']
    
    user = get_user_by_id(session['user_id'])
    premium_active = is_premium_active(session['user_id'])
    
    if not premium_active and user['free_messages'] <= 0:
        return jsonify({'success': False, 'error': 'No free messages left. Please upgrade to premium.'})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if not premium_active:
        cursor.execute("UPDATE users SET free_messages = free_messages - 1 WHERE id = %s", (session['user_id'],))
    
    cursor.execute("INSERT INTO messages (sender_id, receiver_id, message) VALUES (%s, %s, %s)",
                  (session['user_id'], receiver_id, message))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/premium')
def premium():
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    premium_active = is_premium_active(session['user_id'])
    user = get_user_by_id(session['user_id'])
    
    days_left = 0
    if premium_active:
        days_left = get_premium_days_left(session['user_id'])
    
    upi_id = "7678500304@axl"
    amount = 9
    qr_code_img = generate_qr_code(upi_id, amount)
    
    return render_template_string(PREMIUM_HTML, premium_active=premium_active, user=user, 
                                days_left=days_left, qr_code_img=qr_code_img)

@app.route('/verify_payment', methods=['POST'])
def verify_payment():
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    txn_id = request.form['txn_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("INSERT INTO payments (user_id, txn_id, amount, status) VALUES (%s, %s, %s, %s)",
                  (session['user_id'], txn_id, 9, 'pending'))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('premium'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    user = get_user_by_id(session['user_id'])
    unread_messages = get_unread_message_count(session['user_id'])
    
    if request.method == 'POST':
        name = request.form['name']
        mobile = request.form['mobile']
        age = request.form['age']
        gender = request.form['gender']
        
        image = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                image = file.read()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            if image:
                cursor.execute("UPDATE users SET name=%s, mobile=%s, age=%s, gender=%s, image=%s WHERE id=%s",
                              (name, mobile, age, gender, image, session['user_id']))
            else:
                cursor.execute("UPDATE users SET name=%s, mobile=%s, age=%s, gender=%s WHERE id=%s",
                              (name, mobile, age, gender, session['user_id']))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            user = get_user_by_id(session['user_id'])
            return redirect(url_for('profile', success=True))
            
        except Exception as e:
            conn.rollback()
            cursor.close()
            conn.close()
    
    premium_active = is_premium_active(session['user_id'])
    
    profile_image = None
    if user and user['image']:
        try:
            if isinstance(user['image'], bytes):
                profile_image = base64.b64encode(user['image']).decode('utf-8')
        except:
            profile_image = None
    
    return render_template_string(PROFILE_HTML, user=user, premium_active=premium_active, 
                                profile_image=profile_image, unread_messages=unread_messages)

@app.route('/mark_notification_read/<int:notification_id>')
def mark_notification_read_route(notification_id):
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    mark_notification_read(notification_id)
    return jsonify({'success': True})

@app.route('/ignore_like/<int:like_id>')
def ignore_like(like_id):
    if 'user_id' not in session or session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("UPDATE likes SET status = 'ignored' WHERE id = %s", (like_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True})

# Admin Routes
@app.route('/admin_dashboard', methods=['GET', 'POST'])
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    search_term = request.args.get('search', '')
    payment_search = request.args.get('payment_search', '')
    
    if search_term:
        users = search_users(search_term)
    else:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id != 0")
        users = cursor.fetchall()
        cursor.close()
        conn.close()
    
    if payment_search:
        pending_payments = search_payments(payment_search)
        all_payments = search_payments(payment_search)
    else:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT p.*, u.name as user_name FROM payments p JOIN users u ON p.user_id = u.id WHERE p.status = 'pending'")
        pending_payments = cursor.fetchall()
        
        cursor.execute("SELECT p.*, u.name as user_name, u.username, u.is_premium, u.premium_expiry FROM payments p JOIN users u ON p.user_id = u.id ORDER BY p.created_at DESC")
        all_payments = cursor.fetchall()
        cursor.close()
        conn.close()
    
    return render_template_string(ADMIN_DASHBOARD_HTML, users=users, pending_payments=pending_payments, 
                                all_payments=all_payments, search_term=search_term, payment_search=payment_search)

@app.route('/admin_verify_user/<int:user_id>')
def admin_verify_user(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_verified = TRUE WHERE id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin_block_user/<int:user_id>')
def admin_block_user(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_blocked = TRUE WHERE id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin_unblock_user/<int:user_id>')
def admin_unblock_user(user_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_blocked = FALSE WHERE id = %s", (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin_verify_payment/<int:payment_id>')
def admin_verify_payment(payment_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM payments WHERE id = %s", (payment_id,))
    payment = cursor.fetchone()
    
    if payment:
        cursor.execute("UPDATE payments SET status = 'verified' WHERE id = %s", (payment_id,))
        
        expiry_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("UPDATE users SET is_premium = TRUE, premium_expiry = %s WHERE id = %s", 
                      (expiry_date, payment['user_id']))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('admin_dashboard'))

@app.route('/logout')
def logout():
    if 'user_id' in session and not session.get('is_admin'):
        update_user_online_status(session['user_id'], False)
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    # Create static directory for PWA icons
    if not os.path.exists('static'):
        os.makedirs('static')
    
    socketio.run(app, debug=True, host='127.0.0.1', port=5000)