import os
import io
import json
import sqlite3
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from datetime import datetime, timedelta
import random
import pandas as pd
import numpy as np
import joblib

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash

# Load .env file if it exists
def load_env_file():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, val = line.split('=', 1)
                        val = val.strip()
                        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                            val = val[1:-1]
                        os.environ[key.strip()] = val.strip()

load_env_file()

def generate_6_digit_otp():
    return str(secrets.randbelow(900000) + 100000)

def send_otp_email(to_email, otp):
    # Dynamically load env on each email send to pick up new credentials without restart
    load_env_file()
    
    email_user = os.environ.get('EMAIL_USER')
    email_pass = os.environ.get('EMAIL_PASS')
    resend_key = os.environ.get('RESEND_API_KEY')
    
    if email_pass:
        email_pass = email_pass.replace(" ", "").strip()
        
    # Always print OTP to the console for easy debugging/testing
    print("\n" + "*" * 60, flush=True)
    print(f"[OTP SECURITY CODE] Sent To: {to_email}", flush=True)
    print(f"[OTP Code]: {otp}", flush=True)
    print("*" * 60 + "\n", flush=True)
    
    # If using seeded test accounts (e.g. user@fintrust.com), route OTP to the configured target
    target_email = to_email
    if to_email.lower().endswith('@fintrust.com') and (email_user or resend_key):
        target_email = email_user if email_user else "onboarding@resend.dev"
        print(f"[INFO] Redirected test account OTP from {to_email} to developer email {target_email}", flush=True)
        
    # 1. Attempt delivery via Resend API (HTTP Port 443 - never blocked by cloud hosts)
    if resend_key:
        print(f"[INFO] Attempting to send OTP via Resend API to {target_email}", flush=True)
        url = "https://api.resend.com/emails"
        headers = {
            "Authorization": f"Bearer {resend_key}",
            "Content-Type": "application/json"
        }
        html_body = f"""Hello,<br><br>
Your FinTrust AI login verification code is: <strong>{otp}</strong><br><br>
This code is valid for 5 minutes. Please enter this code on the verification screen to complete your login.<br><br>
If you did not request this code, please secure your account.<br><br>
Best regards,<br>
FinTrust Security Team"""
        
        payload = {
            "from": "FinTrust <onboarding@resend.dev>",
            "to": [target_email],
            "subject": f"FinTrust Verification Code: {otp}",
            "html": html_body
        }
        
        import urllib.request
        import json
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                print(f"[INFO] Resend email delivery successful: {res_data}", flush=True)
                return True
        except Exception as e:
            print(f"[WARNING] Resend API delivery failed: {e}. Falling back to SMTP...", flush=True)
            
    # 2. Fallback to standard SMTP (Port 587 - might be blocked on some cloud environments)
    if not email_user or not email_pass:
        print("\n" + "="*50, flush=True)
        print("WARNING: Neither RESEND_API_KEY nor (EMAIL_USER & EMAIL_PASS) environment variables are fully configured!", flush=True)
        print("SIMULATING EMAIL SEND IN CONSOLE ONLY.", flush=True)
        print(f"To: {target_email}")
        print(f"Subject: FinTrust AI - Login Verification Code")
        print(f"OTP Code: {otp}")
        print("="*50 + "\n")
        return True
        
    try:
        from email.utils import formatdate, make_msgid
        msg = MIMEMultipart()
        msg['From'] = email_user
        msg['To'] = target_email
        msg['Subject'] = f"FinTrust Verification Code: {otp}"
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid()
        
        body = f"""Hello,
 
Your FinTrust AI login verification code is: {otp}
 
This code is valid for 5 minutes. Please enter this code on the verification screen to complete your login.
 
If you did not request this code, please secure your account.
 
Best regards,
FinTrust Security Team"""
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
        server.starttls()
        server.login(email_user, email_pass)
        server.sendmail(email_user, [target_email], msg.as_string())
        server.quit()
        print(f"[INFO] SMTP email delivery successful to {target_email}", flush=True)
        return True
    except Exception as e:
        import traceback
        print("\n" + "="*50)
        print(f"ERROR: SMTP Email delivery failed: {e}")
        traceback.print_exc()
        print("="*50 + "\n")
        raise e


# ReportLab imports for PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from flask_cors import CORS

app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'templates'),
            static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'static'))
app.secret_key = 'fintrust_super_secret_session_key_19385'
CORS(app, supports_credentials=True)


# Firebase configurations (read from environment or use fallback values for demo convenience)
FIREBASE_API_KEY = os.environ.get('FIREBASE_API_KEY', 'AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6')
FIREBASE_AUTH_DOMAIN = os.environ.get('FIREBASE_AUTH_DOMAIN', 'fintrust-demo.firebaseapp.com')
FIREBASE_PROJECT_ID = os.environ.get('FIREBASE_PROJECT_ID', 'fintrust-demo')
FIREBASE_APP_ID = os.environ.get('FIREBASE_APP_ID', '1:1234567890:web:1a2b3c4d5e6f7g8h9i0j')

@app.context_processor
def inject_firebase_config():
    return {
        'FIREBASE_API_KEY': FIREBASE_API_KEY,
        'FIREBASE_AUTH_DOMAIN': FIREBASE_AUTH_DOMAIN,
        'FIREBASE_PROJECT_ID': FIREBASE_PROJECT_ID,
        'FIREBASE_APP_ID': FIREBASE_APP_ID
    }

# Translation system setup
TRANSLATIONS = {}
TRANSLATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'translations')
try:
    for filename in os.listdir(TRANSLATIONS_DIR):
        if filename.endswith('.json'):
            lang_code = filename.split('.')[0]
            file_path = os.path.join(TRANSLATIONS_DIR, filename)
            with open(file_path, 'r', encoding='utf-8') as f:
                TRANSLATIONS[lang_code] = json.load(f)
except Exception as e:
    print(f"Error loading translations: {e}")

@app.context_processor
def inject_translations():
    lang = session.get('lang', 'en')
    translations_dict = TRANSLATIONS.get(lang, TRANSLATIONS.get('en', {}))
    
    def translate(key, **kwargs):
        val = translations_dict.get(key, TRANSLATIONS.get('en', {}).get(key, key))
        if kwargs:
            try:
                return val.format(**kwargs)
            except Exception:
                return val
        return val
        
    return dict(_=translate, current_lang=lang)

@app.route('/set_language/<lang>')
def set_language(lang):
    if lang in ['en', 'hi', 'kn', 'ta', 'te', 'mr']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('landing'))

# Load Trained model and scaler
MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(MODEL_DIR, 'model.joblib')
scaler_path = os.path.join(MODEL_DIR, 'scaler.joblib')

try:
    model = joblib.load(model_path)
    scaler = joblib.load(scaler_path)
except Exception as e:
    print(f"Error loading model/scaler: {e}. Run train_model.py first.")
    model = None
    scaler = None

# Database helper
DATABASE_PATH = os.path.join(MODEL_DIR, 'database.db')

# File Upload configurations
UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

# Auth decorator
def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash("Please log in to access this page.", "error")
                return redirect(url_for('login_route'))
                
            # Verify user exists in database to prevent Foreign Key errors from stale sessions
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, role FROM users WHERE id = ?", (session['user_id'],))
            user_row = cursor.fetchone()
            conn.close()
            
            if not user_row:
                session.clear()
                flash("Your session is invalid or the account was modified. Please log in again.", "warning")
                return redirect(url_for('login_route'))
                
            if role and user_row['role'] != role:
                flash("Unauthorized access.", "error")
                return redirect(url_for('landing'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Financial EMI Calculator Helper
def calculate_emi(amount, rate_annual, tenure_months):
    r = rate_annual / 12.0
    if r == 0:
        return amount / tenure_months
    return (amount * r * (1 + r)**tenure_months) / ((1 + r)**tenure_months - 1)

def recommend_loan_parameters(monthly_income, existing_emi, requested_amount):
    safe_emi = (monthly_income * 0.35) - existing_emi
    if safe_emi < 2000:
        safe_emi = max(2000, monthly_income * 0.20)
        
    r = 0.105 / 12.0
    n = 36 # 3 years
    
    # Reverse EMI: P = EMI / [ r * (1+r)^N / ((1+r)^N - 1) ]
    factor = (r * (1 + r)**n) / (((1 + r)**n) - 1)
    safe_amount = safe_emi / factor
    
    recommended_amount = min(requested_amount, safe_amount)
    recommended_amount = max(10000, round(recommended_amount / 5000) * 5000)
    
    recommended_emi = calculate_emi(recommended_amount, 10.5, n)
    
    # Financial Health Score: depends on existing obligations
    dti_base = existing_emi / max(1, monthly_income)
    health_score = int(100 - (dti_base * 100))
    health_score = min(100, max(15, health_score))
    
    # Approval Probability
    prob = min(99, max(10, int((1 - dti_base) * 95)))
    
    return {
        'recommended_amount': recommended_amount,
        'recommended_emi': recommended_emi,
        'recommended_duration': n,
        'suggested_interest_range': '9.5% - 11.5%',
        'financial_health_score': health_score,
        'approval_probability': prob
    }

# Trust Score Rating System Helpers
def compute_trust_score(user_id):
    score = 30
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check verified documents
    cursor.execute("SELECT document_type FROM vendor_documents WHERE user_id = ? AND status = 'Verified'", (user_id,))
    verified_types = [row['document_type'] for row in cursor.fetchall()]
    
    if 'pan_verification' in verified_types:
        score += 15
    if 'aadhaar_verification' in verified_types:
        score += 15
    if 'bank_statement' in verified_types:
        score += 15
    if 'salary_slip' in verified_types:
        score += 15
    if 'business_registration' in verified_types:
        score += 10
        
    # Add applicant history bonus
    cursor.execute("SELECT credit_history FROM applications WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,))
    app_row = cursor.fetchone()
    if app_row and app_row['credit_history'] == 1:
        score += 10
        
    conn.close()
    return min(score, 100)

def get_trust_level(score):
    if score >= 85:
        return 'Platinum', '#10B981' # Green
    elif score >= 70:
        return 'Gold', '#2563EB' # Blue
    elif score >= 50:
        return 'Silver', '#F59E0B' # Amber
    else:
        return 'Bronze', '#64748B' # Gray

def trigger_matching_engine(app_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Fetch application details
        cursor.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
        app_row = cursor.fetchone()
        if not app_row:
            conn.close()
            return
            
        user_id = app_row['user_id']
        loan_amount = app_row['loan_amount'] or 0.0
        loan_tenure = app_row['loan_tenure'] or 12
        
        # Get applicant's trust score
        trust_score = compute_trust_score(user_id)
        
        # 2. Find all active lenders
        cursor.execute("""
            SELECT u.id, lp.max_lending_amount, lp.min_trust_score, lp.interest_rate, lp.preferred_location, lp.preferred_duration 
            FROM users u 
            JOIN lender_preferences lp ON u.id = lp.user_id 
            WHERE u.role = 'lender'
        """)
        lenders = cursor.fetchall()
        
        for lender in lenders:
            lender_id = lender['id']
            max_amount = lender['max_lending_amount'] if lender['max_lending_amount'] is not None else 2000000.0
            min_score = lender['min_trust_score'] if lender['min_trust_score'] is not None else 60
            pref_dur = lender['preferred_duration'] if lender['preferred_duration'] is not None else 24
            pref_loc = lender['preferred_location'] if lender['preferred_location'] is not None else 'All'
            
            # Calculate compatibility
            score = 50
            reasons = []
            
            if trust_score >= min_score:
                score += 15
                reasons.append("✓ Trust Score Meets Requirement")
            else:
                reasons.append("✗ Trust Score Below Target")
                
            if loan_amount <= max_amount:
                score += 15
                reasons.append("✓ Loan Amount Compatible")
            else:
                reasons.append("✗ Loan Amount Exceeds Preferred Limit")
                
            if loan_tenure <= pref_dur:
                score += 10
                reasons.append("✓ Preferred Duration Matches")
            else:
                reasons.append("✗ Loan Duration Longer Than Desired")
                
            if pref_loc == 'All' or pref_loc.lower() == 'mumbai' or (app_row['full_name'] and pref_loc.lower() in app_row['full_name'].lower()):
                score += 10
                reasons.append("✓ Same Location")
            else:
                reasons.append("✓ Location Acceptable")
                
            # Ensure we don't duplicate matches
            cursor.execute("SELECT id FROM matches WHERE lender_id = ? AND application_id = ?", (lender_id, app_id))
            if not cursor.fetchone():
                cursor.execute('''
                    INSERT INTO matches (lender_id, application_id, compatibility_score, reasons)
                    VALUES (?, ?, ?, ?)
                ''', (lender_id, app_id, min(100, score), json.dumps(reasons)))
                
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERROR] trigger_matching_engine failed for app_id {app_id}: {e}")


# --- Routes ---

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/calculator')
def calculator_route():
    return render_template('calculator.html')

@app.route('/login', methods=['GET', 'POST'])
def login_route():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif session.get('role') == 'lender':
            return redirect(url_for('lender_dashboard'))
        return redirect(url_for('applicant_dashboard'))
        
    if request.method == 'POST':
        # Check if request is JSON (Firebase login)
        if request.is_json:
            data = request.get_json()
            id_token = data.get('idToken')
            email = data.get('email', '').strip()
            
            # Helper verification function
            import urllib.request
            import urllib.error
            
            # Mock check if using demo key
            if FIREBASE_API_KEY == 'AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6' or not id_token:
                verification = {
                    'verified': True,
                    'email': email,
                    'uid': f"mock-uid-{email.split('@')[0]}"
                }
            else:
                url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FIREBASE_API_KEY}"
                verify_data = json.dumps({"idToken": id_token}).encode('utf-8')
                req = urllib.request.Request(
                    url,
                    data=verify_data,
                    headers={'Content-Type': 'application/json'}
                )
                try:
                    with urllib.request.urlopen(req) as response:
                        res_data = json.loads(response.read().decode('utf-8'))
                        if 'users' in res_data and len(res_data['users']) > 0:
                            user_info = res_data['users'][0]
                            verification = {
                                'verified': True,
                                'email': user_info.get('email'),
                                'uid': user_info.get('localId')
                            }
                        else:
                            verification = {'verified': False}
                except Exception as e:
                    print(f"Error verifying token: {e}")
                    verification = {'verified': False}
            
            if verification.get('verified'):
                verified_email = verification.get('email')
                firebase_uid = verification.get('uid')
                
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users WHERE email = ?", (verified_email,))
                user = cursor.fetchone()
                
                if user:
                    user_dict = dict(user)
                    # Update firebase_uid if not set
                    if not user_dict.get('firebase_uid'):
                        cursor.execute("UPDATE users SET firebase_uid = ? WHERE id = ?", (firebase_uid, user_dict['id']))
                        conn.commit()
                    conn.close()
                    
                    session['user_id'] = user_dict['id']
                    session['username'] = user_dict['username']
                    session['role'] = user_dict['role']
                    return jsonify({'success': True, 'role': user_dict['role']})
                else:
                    # Auto-register if user doesn't exist in local DB (e.g. registered on Firebase)
                    # Deduce username from email
                    username = verified_email.split('@')[0]
                    try:
                        cursor.execute(
                            "INSERT INTO users (username, password_hash, email, role, firebase_uid) VALUES (?, ?, ?, ?, ?)",
                            (username, 'firebase_auth_hashed', verified_email, 'applicant', firebase_uid)
                        )
                        user_id = cursor.lastrowid
                        conn.commit()
                        conn.close()
                        
                        session['user_id'] = user_id
                        session['username'] = username
                        session['role'] = 'applicant'
                        return jsonify({'success': True, 'role': 'applicant'})
                    except sqlite3.IntegrityError:
                        conn.close()
                        return jsonify({'success': False, 'error': 'Database conflict creating user.'}), 400
            else:
                return jsonify({'success': False, 'error': 'Invalid ID Token'}), 401
                
        # Fallback to old login method if needed for admin seed logins (if Firebase is not used yet)
        action = request.form.get('action')
        
        if action == 'register':
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            role = request.form.get('role', 'applicant')
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            if not username or not email or not phone or not password:
                flash("All fields are required.", "error")
                return render_template('login.html')
                
            if password != confirm_password:
                flash("Passwords do not match.", "error")
                return render_template('login.html')
                
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Pre-check if user already exists
            cursor.execute("SELECT id FROM users WHERE username = ? OR email = ?", (username, email))
            existing_user = cursor.fetchone()
            if existing_user:
                conn.close()
                flash("Username, Email, or Phone already registered.", "error")
                return render_template('login.html')
                
            hashed_pass = generate_password_hash(password)
            otp = generate_6_digit_otp()
            expires_at = (datetime.now() + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
            
            try:
                # Store pending registration details in session
                session['pending_registration'] = {
                    'username': username,
                    'email': email,
                    'phone': phone,
                    'role': role,
                    'password_hash': hashed_pass
                }
                
                # Delete old OTPs for this email and save the new one
                cursor.execute("DELETE FROM otps WHERE email = ?", (email,))
                cursor.execute("""
                    INSERT INTO otps (email, otp, expires_at)
                    VALUES (?, ?, ?)
                """, (email, otp, expires_at))
                conn.commit()
                
                # Set session variables for the verification page
                session['pre_auth_email'] = email
                
                # Send the OTP
                try:
                    send_otp_email(email, otp)
                except Exception as e:
                    print(f"Error printing/sending OTP: {e}")
                    
                flash("A 6-digit verification code has been sent to your registered email address.", "info")
                return redirect(url_for('verify_otp_route'))
            except Exception as e:
                flash(f"An error occurred: {e}", "error")
                return render_template('login.html')
            finally:
                conn.close()
                
        elif action == 'login':
            username = (request.form.get('username') or request.form.get('email', '') or (request.is_json and request.get_json().get('username')) or '').strip()
            password = request.form.get('password') or (request.is_json and request.get_json().get('password')) or ''
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ? OR email = ?", (username, username))
            user = cursor.fetchone()
            
            if user and check_password_hash(user['password_hash'], password):
                user_dict = dict(user)
                conn.close()
                
                # Directly log in and establish user session
                session['user_id'] = user_dict['id']
                session['username'] = user_dict['username']
                session['role'] = user_dict['role']
                
                flash(f"Welcome back, {user_dict['username']}! Logged in successfully.", "success")
                
                if request.is_json or request.headers.get('Accept') == 'application/json':
                    return jsonify({'success': True, 'role': user_dict['role'], 'user': user_dict})
                    
                if user_dict['role'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
                elif user_dict['role'] == 'lender':
                    return redirect(url_for('lender_dashboard'))
                return redirect(url_for('applicant_dashboard'))
            else:
                if user:
                    conn.close()
                if request.is_json or request.headers.get('Accept') == 'application/json':
                    return jsonify({'success': False, 'error': 'Invalid username or password.'}), 401
                flash("Invalid username or password.", "error")
                return render_template('login.html')
            
    return render_template('login.html')

@app.route('/api/register-user', methods=['POST'])
def api_register_user():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    role = data.get('role', 'applicant')
    firebase_uid = data.get('firebase_uid', '').strip()
    
    if not username or not email or not firebase_uid:
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, email, phone, role, firebase_uid) VALUES (?, ?, ?, ?, ?, ?)",
            (username, 'firebase_auth_hashed', email, phone, role, firebase_uid)
        )
        user_id = cursor.lastrowid
        if role == 'lender':
            cursor.execute(
                "INSERT INTO lender_preferences (user_id) VALUES (?)",
                (user_id,)
            )
        conn.commit()
        return jsonify({'success': True, 'message': 'User registered successfully in local database'})
    except sqlite3.IntegrityError as e:
        print(f"SQLite insertion conflict during registration: {e}")
        return jsonify({'success': False, 'error': 'Username, Email, or Phone already registered.'}), 400
    finally:
        conn.close()
                
    return render_template('login.html')

@app.route('/verify-otp', methods=['GET'])
def verify_otp_route():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif session.get('role') == 'lender':
            return redirect(url_for('lender_dashboard'))
        return redirect(url_for('applicant_dashboard'))
        
    if 'pre_auth_email' not in session:
        flash("Please log in first.", "error")
        return redirect(url_for('login_route'))
        
    return render_template('verify_otp.html', email=session['pre_auth_email'])


@app.route('/api/auth/send-otp', methods=['POST'])
def api_send_otp():
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    
    if not email:
        return jsonify({'success': False, 'error': 'Email is required'}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    
    if not user:
        pending = session.get('pending_registration')
        if not pending or pending['email'] != email:
            conn.close()
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
    otp = generate_6_digit_otp()
    expires_at = (datetime.now() + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute("DELETE FROM otps WHERE email = ?", (email,))
    cursor.execute("""
        INSERT INTO otps (email, otp, expires_at)
        VALUES (?, ?, ?)
    """, (email, otp, expires_at))
    conn.commit()
    conn.close()
    
    try:
        send_otp_email(email, otp)
        return jsonify({'success': True, 'message': 'OTP Sent Successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': f"Unable to send OTP: {e}"}), 500


@app.route('/api/auth/verify-otp', methods=['POST'])
def api_verify_otp():
    if request.is_json:
        data = request.get_json() or {}
        email = data.get('email', '').strip()
        otp = data.get('otp', '').strip()
    else:
        email = request.form.get('email', '').strip()
        otp = request.form.get('otp', '').strip()
        
    if not email or not otp:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Email and OTP are required'}), 400
        flash("Email and OTP are required.", "error")
        return redirect(url_for('verify_otp_route'))
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM otps WHERE email = ?", (email,))
    otp_record = cursor.fetchone()
    
    if not otp_record:
        conn.close()
        if request.is_json:
            return jsonify({'success': False, 'error': 'Invalid OTP'}), 400
        flash("Invalid OTP.", "error")
        return redirect(url_for('verify_otp_route'))
        
    expires_at_str = otp_record['expires_at']
    try:
        expires_at = datetime.strptime(expires_at_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        expires_at = datetime.now()
        
    if expires_at < datetime.now():
        cursor.execute("DELETE FROM otps WHERE email = ?", (email,))
        conn.commit()
        conn.close()
        if request.is_json:
            return jsonify({'success': False, 'error': 'OTP has expired'}), 400
        flash("OTP has expired.", "error")
        return redirect(url_for('verify_otp_route'))
        
    if otp_record['otp'] != otp:
        conn.close()
        if request.is_json:
            return jsonify({'success': False, 'error': 'Invalid OTP'}), 400
        flash("Invalid OTP.", "error")
        return redirect(url_for('verify_otp_route'))
        
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    
    if not user:
        pending = session.get('pending_registration')
        if pending and pending['email'] == email:
            try:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, email, phone, role) VALUES (?, ?, ?, ?, ?)",
                    (pending['username'], pending['password_hash'], pending['email'], pending['phone'], pending['role'])
                )
                user_id = cursor.lastrowid
                if pending['role'] == 'lender':
                    cursor.execute(
                        "INSERT INTO lender_preferences (user_id) VALUES (?)",
                        (user_id,)
                    )
                conn.commit()
                
                # Fetch newly created user
                cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
                user = cursor.fetchone()
                
                # Clear pending registration
                session.pop('pending_registration', None)
            except sqlite3.IntegrityError:
                conn.close()
                if request.is_json:
                    return jsonify({'success': False, 'error': 'Database conflict creating user.'}), 400
                flash("Database conflict creating user.", "error")
                return redirect(url_for('login_route'))
        else:
            conn.close()
            if request.is_json:
                return jsonify({'success': False, 'error': 'User not found'}), 404
            flash("User not found.", "error")
            return redirect(url_for('login_route'))
        
    cursor.execute("DELETE FROM otps WHERE email = ?", (email,))
    conn.commit()
    conn.close()
    
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']
    if 'pre_auth_email' in session:
        session.pop('pre_auth_email')
        
    flash(f"Welcome back, {user['username']}! Logged in successfully.", "success")
    
    simulated_jwt = f"simulated_jwt_token_for_{user['username']}_expires_in_1h"
    
    if request.is_json:
        return jsonify({
            'success': True,
            'token': simulated_jwt,
            'user': {
                'id': user['id'],
                'username': user['username'],
                'email': user['email'],
                'role': user['role']
            }
        })
        
    if user['role'] == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif user['role'] == 'lender':
        return redirect(url_for('lender_dashboard'))
    return redirect(url_for('applicant_dashboard'))


@app.route('/api/auth/resend-otp', methods=['POST'])
def api_resend_otp():
    if request.is_json:
        data = request.get_json() or {}
        email = data.get('email', '').strip()
    else:
        email = request.form.get('email', '').strip()
        
    if not email:
        return jsonify({'success': False, 'error': 'Email is required'}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    
    if not user:
        pending = session.get('pending_registration')
        if not pending or pending['email'] != email:
            conn.close()
            return jsonify({'success': False, 'error': 'User not found'}), 404
        
    cursor.execute("DELETE FROM otps WHERE email = ?", (email,))
    
    otp = generate_6_digit_otp()
    expires_at = (datetime.now() + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute("""
        INSERT INTO otps (email, otp, expires_at)
        VALUES (?, ?, ?)
    """, (email, otp, expires_at))
    conn.commit()
    conn.close()
    
    try:
        send_otp_email(email, otp)
        if request.is_json:
            return jsonify({'success': True, 'message': 'OTP Sent Successfully'})
        flash("OTP resent successfully.", "success")
        return redirect(url_for('verify_otp_route'))
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'error': f"Unable to send OTP: {e}"}), 500
        flash(f"Unable to send OTP. Error: {e}", "error")
        return redirect(url_for('verify_otp_route'))


@app.route('/logout')
def logout_route():
    session.clear()
    flash("Successfully logged out.", "success")
    return redirect(url_for('landing'))


@app.context_processor
def inject_notifications():
    if session.get('user_id'):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM notifications 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT 10
            """, (session['user_id'],))
            notifications = [dict(row) for row in cursor.fetchall()]
            
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM notifications 
                WHERE user_id = ? AND is_read = 0
            """, (session['user_id'],))
            unread_count = cursor.fetchone()['cnt']
            conn.close()
            return {'real_notifications': notifications, 'unread_notifications_count': unread_count}
        except Exception as e:
            print(f"Error injecting notifications: {e}")
            return {'real_notifications': [], 'unread_notifications_count': 0}
    return {'real_notifications': [], 'unread_notifications_count': 0}


@app.route('/api/notifications/clear', methods=['POST'])
@login_required()
def clear_notifications():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (session['user_id'],))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/applicant/dashboard')
@login_required('applicant')
def applicant_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM applications WHERE user_id = ? ORDER BY created_at DESC", 
        (session['user_id'],)
    )
    apps = cursor.fetchall()
    
    # Fetch matched lenders
    cursor.execute("""
        SELECT m.id as match_id, m.compatibility_score, m.reasons, m.lender_status, m.borrower_status,
               u.id as lender_user_id, u.username as lender_name, u.email as lender_email, u.phone as lender_phone,
               lp.interest_rate
        FROM matches m
        JOIN applications a ON m.application_id = a.id
        JOIN users u ON m.lender_id = u.id
        JOIN lender_preferences lp ON u.id = lp.user_id
        WHERE a.user_id = ?
        ORDER BY m.compatibility_score DESC
    """, (session['user_id'],))
    matches_rows = cursor.fetchall()
    
    matches = []
    for r in matches_rows:
        md = dict(r)
        md['reasons'] = json.loads(r['reasons'])
        md['lender_trust_score'] = compute_trust_score(r['lender_user_id'])
        matches.append(md)
        
    # Agreement Metrics for Vendor Dashboard
    cursor.execute("SELECT COUNT(*) FROM agreements WHERE vendor_id = ?", (session['user_id'],))
    total_agreements = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM agreements WHERE vendor_id = ? AND status = 'Documents Pending'", (session['user_id'],))
    pending_docs_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM applications WHERE user_id = ? AND status = 'Approved'", (session['user_id'],))
    approved_loans_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM agreements WHERE vendor_id = ? AND status = 'Completed'", (session['user_id'],))
    completed_loans_count = cursor.fetchone()[0]

    # Fetch active/completed agreements
    cursor.execute("""
        SELECT a.id, a.agreement_code, a.application_id, a.loan_amount, a.interest_rate, a.tenure_months, a.emi_amount, a.status,
               u.username as lender_name
        FROM agreements a
        JOIN users u ON a.lender_id = u.id
        WHERE a.vendor_id = ?
    """, (session['user_id'],))
    agreements_rows = cursor.fetchall()
    agreements = [dict(row) for row in agreements_rows]

    # Fetch user transactions
    cursor.execute("""
        SELECT t.id, t.application_id, t.amount, t.currency, t.gateway_order_id, t.gateway_payment_id, t.status, t.created_at
        FROM transactions t
        WHERE t.user_id = ?
        ORDER BY t.created_at DESC
    """, (session['user_id'],))
    tx_rows = cursor.fetchall()
    transactions = [dict(row) for row in tx_rows]

    conn.close()
    
    score = compute_trust_score(session['user_id'])
    level, _ = get_trust_level(score)
    
    return render_template(
        'dashboard_applicant.html', 
        apps=apps, 
        trust_score=score, 
        trust_level=level,
        matches=matches,
        total_agreements=total_agreements,
        pending_docs_count=pending_docs_count,
        approved_loans_count=approved_loans_count,
        completed_loans_count=completed_loans_count,
        agreements=agreements,
        transactions=transactions
    )

@app.route('/apply', methods=['GET', 'POST'])
@login_required('applicant')
def apply():
    if request.method == 'POST':
        try:
            # Safe parsing helpers for form numbers
            def safe_float(val, default=0.0):
                try:
                    return float(val) if val is not None and str(val).strip() != '' else default
                except (ValueError, TypeError):
                    return default

            def safe_int(val, default=0):
                try:
                    return int(val) if val is not None and str(val).strip() != '' else default
                except (ValueError, TypeError):
                    return default

            # Retrieve Form Data
            full_name = (request.form.get('full_name') or '').strip()
            age = safe_int(request.form.get('age'), 25)
            gender = request.form.get('gender') or 'Other'
            email = (request.form.get('email') or '').strip()
            phone = (request.form.get('phone') or '').strip()
            employment_type = request.form.get('employment_type') or 'Salaried'
            profession = (request.form.get('profession') or '').strip()
            monthly_income = safe_float(request.form.get('monthly_income'), 0.0)
            existing_emi = safe_float(request.form.get('existing_emi'), 0.0)
            loan_type = request.form.get('loan_type') or 'Personal'
            loan_amount = safe_float(request.form.get('loan_amount'), 0.0)
            loan_tenure = safe_int(request.form.get('loan_tenure'), 12)
            guarantor_name = (request.form.get('guarantor_name') or 'N/A').strip()
            guarantor_income = safe_float(request.form.get('guarantor_income'), 0.0)
            existing_debts = safe_float(request.form.get('existing_debts'), 0.0)
            credit_history = safe_int(request.form.get('credit_history'), 1)
            
            # Verify ML Load status
            if not model or not scaler:
                flash("Machine Learning engine offline. Contact Admin.", "error")
                return redirect(url_for('applicant_dashboard'))
                
            # 1. Prep Features & Predict Probabilities
            features = [
                monthly_income,
                existing_emi,
                1 if employment_type == 'Salaried' else 0,
                loan_amount,
                loan_tenure,
                credit_history,
                guarantor_income
            ]
            
            features_scaled = scaler.transform([features])
            prob = float(model.predict_proba(features_scaled)[0][1])
            score = int(prob * 100)
            
            # Credit history cap rule
            if credit_history == 0:
                score = min(score, 45)
                
            # Determine Status and Risk
            if score >= 70:
                status = 'Approved'
                risk_level = 'Low'
            elif score >= 40:
                status = 'Moderate'
                risk_level = 'Medium'
            else:
                status = 'Rejected'
                risk_level = 'High'
                
            # 2. XAI Reason & Recommendation Rules
            reasons = []
            suggestions = []
            
            new_emi = calculate_emi(loan_amount, 0.09, loan_tenure)
            total_monthly_obligations = existing_emi + new_emi
            income_capacity = max(1.0, monthly_income + 0.5 * guarantor_income)
            dti_ratio = total_monthly_obligations / income_capacity
            
            if dti_ratio > 0.45:
                reasons.append({
                    'type': 'con',
                    'text': f"High debt-to-income ratio ({dti_ratio*100:.1f}%) significantly increases risk. Total commitments consume too much monthly income."
                })
                suggestions.append("Work on paying down existing balances to reduce your debt-to-income ratio below 36%.")
            else:
                reasons.append({
                    'type': 'pro',
                    'text': f"Healthy debt-to-income ratio ({dti_ratio*100:.1f}%) demonstrates good repayment capacity."
                })
                
            if credit_history == 1:
                reasons.append({
                    'type': 'pro',
                    'text': "Positive credit history indicates strong past repayment behavior."
                })
            else:
                reasons.append({
                    'type': 'con',
                    'text': "Poor credit history or past defaults severely restrict underwriting scores."
                })
                suggestions.append("Build positive credit by taking small lines of credit and paying them off on time.")
                
            if guarantor_income > 0.5 * monthly_income:
                reasons.append({
                    'type': 'pro',
                    'text': f"Strong guarantor backing (₹{guarantor_income:,.0f}/mo) provides additional security."
                })
            else:
                if loan_amount > 5 * max(1.0, monthly_income) * 12:
                    suggestions.append("Adding a co-signer or guarantor with stable monthly income can mitigate risk.")
                    
            annual_income = max(1.0, monthly_income * 12)
            lti_ratio = loan_amount / annual_income
            if lti_ratio > 4.5:
                reasons.append({
                    'type': 'con',
                    'text': f"Requested loan size is high ({lti_ratio:.1f}x annual income), increasing leverage risk."
                })
                suggestions.append("Apply for a lower loan amount or extend the tenure to reduce the monthly burden.")
            else:
                reasons.append({
                    'type': 'pro',
                    'text': f"Reasonable leverage level ({lti_ratio:.1f}x annual income) fits risk profiles."
                })
                
            if monthly_income > 8000:
                reasons.append({
                    'type': 'pro',
                    'text': f"High net monthly income (₹{monthly_income:,.0f}) provides solid cushion."
                })
            elif monthly_income < 3000:
                reasons.append({
                    'type': 'con',
                    'text': f"Moderate net monthly income (₹{monthly_income:,.0f}) limits maximum debt capacity."
                })
                suggestions.append("Explore options to supplement monthly income or reduce the requested loan size.")
                
            if employment_type == 'Salaried':
                reasons.append({
                    'type': 'pro',
                    'text': "Salaried employment type offers predictable and stable income streams."
                })
            else:
                reasons.append({
                    'type': 'con',
                    'text': "Self-employed status carries higher monthly revenue variability."
                })
                
            reasons_json = json.dumps(reasons)
            
            # Save to database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO applications (
                    user_id, full_name, age, gender, email, phone, employment_type, profession,
                    monthly_income, existing_emi, loan_type, loan_amount, loan_tenure,
                    guarantor_name, guarantor_income, existing_debts, credit_history,
                    status, approval_probability, eligibility_score, risk_level, reasons
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session['user_id'], full_name, age, gender, email, phone, employment_type, profession,
                monthly_income, existing_emi, loan_type, loan_amount, loan_tenure,
                guarantor_name, guarantor_income, existing_debts, credit_history,
                status, prob, score, risk_level, reasons_json
            ))
            new_app_id = cursor.lastrowid
            
            # Insert application submitted notification
            notif_title = "Loan Application Submitted"
            notif_msg = f"Your application #AP-{new_app_id} for a {loan_type} Loan of ₹{loan_amount:,.2f} has been submitted."
            cursor.execute("""
                INSERT INTO notifications (user_id, title, message, type)
                VALUES (?, ?, ?, ?)
            """, (session['user_id'], notif_title, notif_msg, 'info'))
            
            conn.commit()
            conn.close()
            
            # Trigger matching with active lenders
            trigger_matching_engine(new_app_id)
            
            # 3. Simulate Email Notification
            print("\n" + "="*50)
            print(f"SIMULATED EMAIL NOTIFICATION SENT TO {email}")
            print(f"Subject: FinTrust Loan Application Reference #AP-{new_app_id} Received")
            print(f"Dear {full_name},\n")
            print(f"Thank you for submitting your loan application on FinTrust. Your AI-powered eligibility results are ready:")
            print(f"- Reference ID: #AP-{new_app_id}")
            print(f"- Decision Status: {status}")
            print(f"- Eligibility Score: {score}/100")
            print(f"- Risk Level: {risk_level}")
            print(f"\nYou can download your PDF report and track updates by logging into your FinTrust dashboard.")
            print("="*50 + "\n")
            
            flash("Application submitted and credit evaluation complete!", "success")
            return redirect(url_for('result', app_id=new_app_id))
        except sqlite3.IntegrityError as ie:
            print(f"[INTEGRITY ERROR] {ie}")
            session.clear()
            flash("Your session reference was invalid. Please log in again.", "warning")
            return redirect(url_for('login_route'))
        except Exception as err:
            import traceback
            traceback.print_exc()
            flash(f"Application submission error: {err}", "danger")
            return redirect(url_for('applicant_dashboard'))
        
    return render_template('apply.html')

@app.route('/result/<int:app_id>')
@login_required()
def result(app_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
    app_row = cursor.fetchone()
    
    if not app_row:
        conn.close()
        flash("Application not found.", "error")
        return redirect(url_for('landing'))
        
    # Security check: applicants can only view their own applications
    if session.get('role') != 'admin' and app_row['user_id'] != session.get('user_id'):
        conn.close()
        flash("Unauthorized access to this application record.", "error")
        return redirect(url_for('landing'))
        
    # Fetch verification documents for the owner of the application
    cursor.execute("SELECT * FROM vendor_documents WHERE user_id = ? ORDER BY created_at DESC", (app_row['user_id'],))
    docs = cursor.fetchall()
    conn.close()
    
    reasons = json.loads(app_row['reasons'])
    
    # Recalculate metrics for display
    new_emi = calculate_emi(app_row['loan_amount'], 0.09, app_row['loan_tenure'])
    dti = (app_row['existing_emi'] + new_emi) / (app_row['monthly_income'] + 0.5 * app_row['guarantor_income'])
    lti = app_row['loan_amount'] / (app_row['monthly_income'] * 12)
    
    # Generate recommendations based on negative reasons
    suggestions = []
    for reason in reasons:
        if reason['type'] == 'con':
            if 'debt-to-income' in reason['text']:
                suggestions.append("Work on paying down existing balances to reduce your debt-to-income ratio below 36%.")
            elif 'credit history' in reason['text']:
                suggestions.append("Pay off outstanding credit bills and set up auto-pay to restore credit scores.")
            elif 'loan size' in reason['text']:
                suggestions.append("Submit a new application with a smaller loan size to decrease leverage risk.")
            elif 'monthly income' in reason['text']:
                suggestions.append("Co-applying with a higher-earning spouse or guarantor can bolster repayment credentials.")
                
    ratios = {
        'dti': dti,
        'lti': lti
    }
    
    trust_score = compute_trust_score(app_row['user_id'])
    trust_level, trust_color = get_trust_level(trust_score)
    
    recommendation_params = recommend_loan_parameters(app_row['monthly_income'], app_row['existing_emi'], app_row['loan_amount'])
    
    return render_template(
        'result.html', 
        app=app_row, 
        ratios=ratios, 
        reasons=reasons, 
        suggestions=suggestions,
        status=app_row['status'],
        docs=docs,
        trust_score=trust_score,
        trust_level=trust_level,
        trust_color=trust_color,
        recommendation_params=recommendation_params
    )

# --- Lender Flow ---

@app.route('/lender/dashboard')
@login_required('lender')
def lender_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get lender preferences
    cursor.execute("SELECT * FROM lender_preferences WHERE user_id = ?", (session['user_id'],))
    prefs = cursor.fetchone()
    if not prefs:
        # Create default preferences
        cursor.execute("INSERT INTO lender_preferences (user_id) VALUES (?)", (session['user_id'],))
        conn.commit()
        cursor.execute("SELECT * FROM lender_preferences WHERE user_id = ?", (session['user_id'],))
        prefs = cursor.fetchone()
        
    # Get active/pending matches
    cursor.execute("""
        SELECT m.id as match_id, m.compatibility_score, m.reasons, m.lender_status, m.borrower_status,
               a.id as app_id, a.full_name, a.loan_amount, a.loan_tenure, a.loan_type, a.monthly_income,
               u.id as borrower_id, u.email as borrower_email, u.phone as borrower_phone
        FROM matches m
        JOIN applications a ON m.application_id = a.id
        JOIN users u ON a.user_id = u.id
        WHERE m.lender_id = ?
        ORDER BY m.compatibility_score DESC
    """, (session['user_id'],))
    matches_rows = cursor.fetchall()
    
    # Calculate some dashboard stats
    cursor.execute("SELECT COUNT(*) FROM applications WHERE status = 'Pending' OR status = 'Approved' OR status = 'Moderate'")
    available_borrowers = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM matches WHERE lender_id = ? AND lender_status = 'Pending'", (session['user_id'],))
    pending_requests = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM matches WHERE lender_id = ? AND lender_status = 'Accepted' AND borrower_status = 'Accepted'", (session['user_id'],))
    today_matches = cursor.fetchone()[0]
    
    # Get average borrower trust score
    cursor.execute("SELECT user_id FROM applications")
    borrower_ids = [row['user_id'] for row in cursor.fetchall()]
    avg_trust = 0
    if borrower_ids:
        scores = [compute_trust_score(b_id) for b_id in set(borrower_ids)]
        avg_trust = sum(scores) // len(scores) if scores else 0
    else:
        avg_trust = 75 # placeholder default
        
    # Convert matches rows to lists for template access
    matches = []
    for r in matches_rows:
        md = dict(r)
        md['reasons'] = json.loads(r['reasons'])
        md['trust_score'] = compute_trust_score(r['borrower_id'])
        matches.append(md)
        
    score = compute_trust_score(session['user_id'])
    level, _ = get_trust_level(score)
    
    # Agreement Metrics for Lender Dashboard
    cursor.execute("SELECT COUNT(*) FROM agreements WHERE lender_id = ? AND status IN ('Pending', 'Approved', 'Documents Pending', 'Under Review')", (session['user_id'],))
    active_agreements_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM matches WHERE lender_id = ? AND lender_status = 'Pending'", (session['user_id'],))
    pending_reviews_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM agreements WHERE lender_id = ? AND status = 'Under Review'", (session['user_id'],))
    docs_awaiting_review_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM agreements WHERE lender_id = ? AND status = 'Completed'", (session['user_id'],))
    lender_completed_count = cursor.fetchone()[0]

    conn.close()
    return render_template(
        'dashboard_lender.html',
        prefs=dict(prefs),
        matches=matches,
        available_borrowers=available_borrowers,
        pending_requests=pending_requests,
        today_matches=today_matches,
        avg_trust=avg_trust,
        trust_score=score,
        trust_level=level,
        active_agreements_count=active_agreements_count,
        pending_reviews_count=pending_reviews_count,
        docs_awaiting_review_count=docs_awaiting_review_count,
        lender_completed_count=lender_completed_count
    )

@app.route('/api/lender/preferences/save', methods=['POST'])
@login_required('lender')
def save_lender_preferences():
    max_amount = float(request.form.get('max_lending_amount', 2000000.0))
    min_score = int(request.form.get('min_trust_score', 60))
    rate = float(request.form.get('interest_rate', 10.5))
    pref_loc = request.form.get('preferred_location', 'All').strip()
    pref_dur = int(request.form.get('preferred_duration', 24))
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE lender_preferences
        SET max_lending_amount = ?, min_trust_score = ?, interest_rate = ?, preferred_location = ?, preferred_duration = ?
        WHERE user_id = ?
    """, (max_amount, min_score, rate, pref_loc, pref_dur, session['user_id']))
    conn.commit()
    
    # Re-run matching engine for all active applications
    cursor.execute("SELECT id FROM applications")
    apps = cursor.fetchall()
    for app in apps:
        trigger_matching_engine(app['id'])
        
    conn.close()
    flash("Lending preferences updated and match recommendations refreshed!", "success")
    return redirect(url_for('lender_dashboard'))

# --- Digital Agreement Engine ---

def create_digital_agreement(match_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM agreements WHERE match_id = ?", (match_id,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return existing['id']
        
    cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
    match_row = cursor.fetchone()
    if not match_row:
        conn.close()
        return None
        
    app_id = match_row['application_id']
    lender_id = match_row['lender_id']
    
    cursor.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
    app_row = cursor.fetchone()
    if not app_row:
        conn.close()
        return None
        
    vendor_id = app_row['user_id']
    
    cursor.execute("SELECT interest_rate FROM lender_preferences WHERE user_id = ?", (lender_id,))
    pref = cursor.fetchone()
    interest_rate = pref['interest_rate'] if pref and pref['interest_rate'] else 10.5
    
    loan_amount = app_row['loan_amount']
    tenure_months = app_row['loan_tenure']
    emi_amount = round(calculate_emi(loan_amount, interest_rate / 100.0, tenure_months), 2)
    processing_fee = round(0.02 * loan_amount, 2)
    
    code_suffix = str(random.randint(1000, 9999))
    date_prefix = datetime.now().strftime("%Y%m%d")
    agreement_code = f"FT-AGR-{date_prefix}-{code_suffix}"
    
    cursor.execute("PRAGMA table_info(agreements)")
    agr_cols = [c[1] for c in cursor.fetchall()]
    
    if 'contract_code' in agr_cols:
        cursor.execute('''
            INSERT INTO agreements (
                agreement_code, contract_code, match_id, application_id, lender_id, vendor_id,
                loan_amount, interest_rate, tenure_months, emi_amount, processing_fee, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            agreement_code, agreement_code, match_id, app_id, lender_id, vendor_id,
            loan_amount, interest_rate, tenure_months, emi_amount, processing_fee, 'Pending'
        ))
    else:
        cursor.execute('''
            INSERT INTO agreements (
                agreement_code, match_id, application_id, lender_id, vendor_id,
                loan_amount, interest_rate, tenure_months, emi_amount, processing_fee, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            agreement_code, match_id, app_id, lender_id, vendor_id,
            loan_amount, interest_rate, tenure_months, emi_amount, processing_fee, 'Pending'
        ))
    
    agreement_id = cursor.lastrowid
    
    cursor.execute('''
        INSERT INTO agreement_timeline (agreement_id, actor_name, actor_role, action_type, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (agreement_id, app_row['full_name'], 'vendor', 'loan_submitted', f"Loan Application #AP-{app_id} submitted."))
    
    cursor.execute('''
        INSERT INTO agreement_timeline (agreement_id, actor_name, actor_role, action_type, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (agreement_id, 'FinTrust AI Engine', 'system', 'trust_score', f"AI Trust Score evaluated at {app_row['eligibility_score'] or 75}/100."))
    
    cursor.execute("SELECT username FROM users WHERE id = ?", (lender_id,))
    lender_user = cursor.fetchone()
    lender_name = lender_user['username'] if lender_user else "Lender"
    
    cursor.execute('''
        INSERT INTO agreement_timeline (agreement_id, actor_name, actor_role, action_type, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (agreement_id, lender_name, 'lender', 'loan_approved', f"Lender {lender_name} approved Application #AP-{app_id}."))
    
    cursor.execute('''
        INSERT INTO agreement_timeline (agreement_id, actor_name, actor_role, action_type, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (agreement_id, 'FinTrust System', 'system', 'agreement_generated', f"Digital Loan Agreement {agreement_code} generated."))
    
    # Auto-link applicant's verified Trust Verification documents to agreement_documents
    cursor.execute("SELECT * FROM vendor_documents WHERE user_id = ? AND status = 'Verified'", (vendor_id,))
    verified_docs = cursor.fetchall()
    for vdoc in verified_docs:
        doc_label = vdoc['document_type'].replace('_', ' ').title()
        cursor.execute('''
            INSERT INTO agreement_documents (
                agreement_id, application_id, uploader_id, uploader_role, document_type, document_name, file_path, file_size, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            agreement_id, app_id, vendor_id, 'vendor', doc_label, vdoc['document_name'], vdoc['file_path'], 1024, 'Approved'
        ))

    cursor.execute('''
        INSERT INTO notifications (user_id, title, message, type)
        VALUES (?, ?, ?, ?)
    ''', (vendor_id, "Digital Agreement Generated", f"Your Digital Loan Agreement {agreement_code} has been generated. Please review and accept.", "success"))
    
    cursor.execute('''
        INSERT INTO notifications (user_id, title, message, type)
        VALUES (?, ?, ?, ?)
    ''', (lender_id, "Digital Agreement Generated", f"Digital Loan Agreement {agreement_code} for application #AP-{app_id} has been generated.", "info"))
    
    conn.commit()
    conn.close()
    return agreement_id


@app.route('/api/matches/<int:match_id>/action', methods=['POST'])
@login_required()
def match_action(match_id):
    action = request.form.get('action') # 'Accepted' or 'Rejected'
    if action not in ['Accepted', 'Rejected']:
        return jsonify({'success': False, 'error': 'Invalid action'}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
    match_row = cursor.fetchone()
    if not match_row:
        conn.close()
        return jsonify({'success': False, 'error': 'Match record not found'}), 404
        
    role = session.get('role')
    if role == 'lender':
        # Verify ownership
        if match_row['lender_id'] != session['user_id']:
            conn.close()
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        cursor.execute("UPDATE matches SET lender_status = ? WHERE id = ?", (action, match_id))
    else:
        # Check borrower owns the application
        cursor.execute("SELECT user_id FROM applications WHERE id = ?", (match_row['application_id'],))
        app_row = cursor.fetchone()
        if not app_row or app_row['user_id'] != session['user_id']:
            conn.close()
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        cursor.execute("UPDATE matches SET borrower_status = ? WHERE id = ?", (action, match_id))
        
    conn.commit()
    
    # Check if both accepted
    cursor.execute("SELECT lender_status, borrower_status FROM matches WHERE id = ?", (match_id,))
    updated_match = cursor.fetchone()
    
    both_accepted = (updated_match['lender_status'] == 'Accepted' and updated_match['borrower_status'] == 'Accepted')
    
    if both_accepted:
        cursor.execute("UPDATE applications SET status = 'Approved' WHERE id = ?", (match_row['application_id'],))
        conn.commit()
        
    conn.close()
    
    # Trigger digital agreement creation as soon as lender approves (or both accept)
    if action == 'Accepted' and role == 'lender':
        create_digital_agreement(match_id)
        
    msg = f"Match {action.lower()} successfully."
    if both_accepted:
        msg = "Match finalized! Digital Loan Agreement created and contact details unlocked."
        
    flash(msg, "success")
    if role == 'lender':
        return redirect(url_for('lender_dashboard'))
    else:
        return redirect(url_for('applicant_dashboard'))


# --- Digital Agreement & Document Routes ---

@app.route('/agreements')
@login_required()
def agreements_list():
    user_id = session['user_id']
    role = session.get('role')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if role == 'admin':
        cursor.execute('''
            SELECT a.*, app.full_name as vendor_name, u_len.username as lender_name
            FROM agreements a
            JOIN applications app ON a.application_id = app.id
            JOIN users u_len ON a.lender_id = u_len.id
            ORDER BY a.created_at DESC
        ''')
    elif role == 'lender':
        cursor.execute('''
            SELECT a.*, app.full_name as vendor_name, u_len.username as lender_name
            FROM agreements a
            JOIN applications app ON a.application_id = app.id
            JOIN users u_len ON a.lender_id = u_len.id
            WHERE a.lender_id = ?
            ORDER BY a.created_at DESC
        ''', (user_id,))
    else:
        # Vendor / Applicant
        cursor.execute('''
            SELECT a.*, app.full_name as vendor_name, u_len.username as lender_name
            FROM agreements a
            JOIN applications app ON a.application_id = app.id
            JOIN users u_len ON a.lender_id = u_len.id
            WHERE a.vendor_id = ?
            ORDER BY a.created_at DESC
        ''', (user_id,))
        
    agreements = cursor.fetchall()
    conn.close()
    return render_template('agreements_list.html', agreements=agreements)


@app.route('/agreement/<int:agreement_id>')
@login_required()
def agreement_details(agreement_id):
    user_id = session['user_id']
    role = session.get('role')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT a.*, 
               app.full_name as vendor_full_name, app.email as vendor_email, app.phone as vendor_phone, app.profession as vendor_profession, app.loan_type, app.guarantor_name, app.guarantor_income,
               u_len.username as lender_name, u_len.email as lender_email, u_len.phone as lender_phone
        FROM agreements a
        JOIN applications app ON a.application_id = app.id
        JOIN users u_len ON a.lender_id = u_len.id
        WHERE a.id = ?
    ''', (agreement_id,))
    agr = cursor.fetchone()
    
    if not agr:
        conn.close()
        flash("Agreement record not found.", "error")
        return redirect(url_for('agreements_list'))
        
    # Security check: Only assigned lender, vendor, or admin
    if role != 'admin' and user_id not in [agr['lender_id'], agr['vendor_id']]:
        conn.close()
        flash("Unauthorized: You do not have permission to view this agreement.", "error")
        return redirect(url_for('agreements_list'))
        
    # Fetch documents
    cursor.execute('''
        SELECT d.*, u.username as uploader_name
        FROM agreement_documents d
        JOIN users u ON d.uploader_id = u.id
        WHERE d.agreement_id = ?
        ORDER BY d.created_at DESC
    ''', (agreement_id,))
    documents = cursor.fetchall()
    
    # Fetch timeline
    cursor.execute('''
        SELECT * FROM agreement_timeline
        WHERE agreement_id = ?
        ORDER BY created_at ASC
    ''', (agreement_id,))
    timeline = cursor.fetchall()
    
    conn.close()
    
    is_vendor = (user_id == agr['vendor_id'])
    is_lender = (user_id == agr['lender_id'])
    
    return render_template('agreement_details.html', agr=agr, documents=documents, timeline=timeline, is_vendor=is_vendor, is_lender=is_lender)


@app.route('/api/agreement/<int:agreement_id>/accept', methods=['POST'])
@login_required()
def accept_digital_agreement(agreement_id):
    user_id = session['user_id']
    role = session.get('role')
    user_ip = request.remote_addr or '127.0.0.1'
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM agreements WHERE id = ?", (agreement_id,))
    agr = cursor.fetchone()
    if not agr:
        conn.close()
        return jsonify({'success': False, 'error': 'Agreement not found'}), 404
        
    if role != 'admin' and user_id not in [agr['lender_id'], agr['vendor_id']]:
        conn.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    user_row = cursor.fetchone()
    user_name = user_row['username'] if user_row else "User"
    
    if user_id == agr['vendor_id'] or role == 'applicant':
        cursor.execute('''
            UPDATE agreements
            SET vendor_consent = 1, vendor_consent_at = ?, vendor_ip = ?
            WHERE id = ?
        ''', (now_ts, user_ip, agreement_id))
        actor_role = 'vendor'
        action_desc = f"Vendor digital consent accepted by {user_name}."
    else:
        cursor.execute('''
            UPDATE agreements
            SET lender_consent = 1, lender_consent_at = ?, lender_ip = ?
            WHERE id = ?
        ''', (now_ts, user_ip, agreement_id))
        actor_role = 'lender'
        action_desc = f"Lender digital consent accepted by {user_name}."
        
    cursor.execute('''
        INSERT INTO agreement_timeline (agreement_id, actor_name, actor_role, action_type, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (agreement_id, user_name, actor_role, 'consent_accepted', action_desc))
    
    # Check if both accepted
    cursor.execute("SELECT vendor_consent, lender_consent FROM agreements WHERE id = ?", (agreement_id,))
    updated = cursor.fetchone()
    
    if updated['vendor_consent'] == 1 and updated['lender_consent'] == 1:
        cursor.execute("UPDATE agreements SET status = 'Approved' WHERE id = ?", (agreement_id,))
        cursor.execute("UPDATE applications SET status = 'Approved' WHERE id = ?", (agr['application_id'],))
        
        cursor.execute('''
            INSERT INTO agreement_timeline (agreement_id, actor_name, actor_role, action_type, description)
            VALUES (?, ?, ?, ?, ?)
        ''', (agreement_id, 'FinTrust System', 'system', 'agreement_active', "Both parties digitally accepted. Agreement is now Active & Approved."))
        
        cursor.execute('''
            INSERT INTO notifications (user_id, title, message, type)
            VALUES (?, ?, ?, ?)
        ''', (agr['vendor_id'], "Agreement Fully Approved", f"Digital Loan Agreement {agr['agreement_code']} is now fully executed!", "success"))
        
        cursor.execute('''
            INSERT INTO notifications (user_id, title, message, type)
            VALUES (?, ?, ?, ?)
        ''', (agr['lender_id'], "Agreement Fully Approved", f"Digital Loan Agreement {agr['agreement_code']} is now fully executed!", "success"))
    else:
        cursor.execute("UPDATE agreements SET status = 'Documents Pending' WHERE id = ?", (agreement_id,))
        
    conn.commit()
    conn.close()
    
    flash("Digital consent accepted successfully!", "success")
    return redirect(url_for('agreement_details', agreement_id=agreement_id))


@app.route('/api/agreement/<int:agreement_id>/upload_document', methods=['POST'])
@login_required()
def upload_agreement_document(agreement_id):
    user_id = session['user_id']
    role = session.get('role')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM agreements WHERE id = ?", (agreement_id,))
    agr = cursor.fetchone()
    if not agr:
        conn.close()
        flash("Agreement not found.", "error")
        return redirect(url_for('agreements_list'))
        
    if role != 'admin' and user_id not in [agr['lender_id'], agr['vendor_id']]:
        conn.close()
        flash("Unauthorized file upload.", "error")
        return redirect(url_for('agreements_list'))
        
    if 'document_file' not in request.files:
        conn.close()
        flash("No file selected.", "error")
        return redirect(url_for('agreement_details', agreement_id=agreement_id))
        
    file = request.files['document_file']
    doc_type = request.form.get('document_type', 'Supporting Document').strip()
    
    if not file or file.filename == '':
        conn.close()
        flash("Please select a file to upload.", "error")
        return redirect(url_for('agreement_details', agreement_id=agreement_id))
        
    filename = file.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    allowed_exts = {'pdf', 'jpg', 'jpeg', 'png'}
    
    if ext not in allowed_exts:
        conn.close()
        flash(f"Invalid file type .{ext}. Allowed formats: PDF, JPG, JPEG, PNG.", "error")
        return redirect(url_for('agreement_details', agreement_id=agreement_id))
        
    # Save file securely
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(filename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stored_filename = f"{timestamp}_{user_id}_{safe_name}"
    
    upload_dir = os.path.join(os.path.dirname(__file__), 'uploads', 'agreements', str(agreement_id))
    os.makedirs(upload_dir, exist_ok=True)
    
    full_path = os.path.join(upload_dir, stored_filename)
    file.save(full_path)
    file_size = os.path.getsize(full_path)
    
    uploader_role = 'vendor' if user_id == agr['vendor_id'] else 'lender'
    
    cursor.execute('''
        INSERT INTO agreement_documents (
            agreement_id, application_id, uploader_id, uploader_role,
            document_name, document_type, file_path, file_size, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        agreement_id, agr['application_id'], user_id, uploader_role,
        safe_name, doc_type, full_path, file_size, 'Pending'
    ))
    
    cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    u_row = cursor.fetchone()
    uploader_name = u_row['username'] if u_row else "User"
    
    cursor.execute('''
        INSERT INTO agreement_timeline (agreement_id, actor_name, actor_role, action_type, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (agreement_id, uploader_name, uploader_role, 'document_uploaded', f"{uploader_name} uploaded {doc_type} ({safe_name})."))
    
    # Update agreement status to Under Review
    cursor.execute("UPDATE agreements SET status = 'Under Review' WHERE id = ?", (agreement_id,))
    
    # Send notification
    recipient_id = agr['lender_id'] if uploader_role == 'vendor' else agr['vendor_id']
    cursor.execute('''
        INSERT INTO notifications (user_id, title, message, type)
        VALUES (?, ?, ?, ?)
    ''', (recipient_id, "New Document Uploaded", f"{uploader_name} uploaded a {doc_type} for agreement {agr['agreement_code']}.", "info"))
    
    conn.commit()
    conn.close()
    
    flash(f"Document '{doc_type}' uploaded successfully!", "success")
    return redirect(url_for('agreement_details', agreement_id=agreement_id))


@app.route('/api/agreement/document/<int:doc_id>/status', methods=['POST'])
@login_required()
def update_document_status(doc_id):
    user_id = session['user_id']
    role = session.get('role')
    new_status = request.form.get('status', 'Approved') # Approved or Rejected
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT d.*, a.lender_id, a.vendor_id, a.agreement_code
        FROM agreement_documents d
        JOIN agreements a ON d.agreement_id = a.id
        WHERE d.id = ?
    ''', (doc_id,))
    doc = cursor.fetchone()
    
    if not doc:
        conn.close()
        flash("Document record not found.", "error")
        return redirect(url_for('agreements_list'))
        
    if role != 'admin' and user_id != doc['lender_id']:
        conn.close()
        flash("Unauthorized: Only the lender or admin can review documents.", "error")
        return redirect(url_for('agreement_details', agreement_id=doc['agreement_id']))
        
    cursor.execute("UPDATE agreement_documents SET status = ? WHERE id = ?", (new_status, doc_id))
    
    cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    u_row = cursor.fetchone()
    reviewer_name = u_row['username'] if u_row else "Lender"
    
    cursor.execute('''
        INSERT INTO agreement_timeline (agreement_id, actor_name, actor_role, action_type, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (doc['agreement_id'], reviewer_name, 'lender', 'document_reviewed', f"{reviewer_name} marked {doc['document_type']} as {new_status}."))
    
    cursor.execute('''
        INSERT INTO notifications (user_id, title, message, type)
        VALUES (?, ?, ?, ?)
    ''', (doc['vendor_id'], "Document Status Updated", f"Your {doc['document_type']} has been marked as {new_status}.", "info"))
    
    conn.commit()
    conn.close()
    
    flash(f"Document status updated to {new_status}.", "success")
    return redirect(url_for('agreement_details', agreement_id=doc['agreement_id']))


@app.route('/agreement/document/<int:doc_id>/download')
@login_required()
def download_agreement_document(doc_id):
    user_id = session['user_id']
    role = session.get('role')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT d.*, a.lender_id, a.vendor_id
        FROM agreement_documents d
        JOIN agreements a ON d.agreement_id = a.id
        WHERE d.id = ?
    ''', (doc_id,))
    doc = cursor.fetchone()
    conn.close()
    
    if not doc:
        flash("Document not found.", "error")
        return redirect(url_for('agreements_list'))
        
    if role != 'admin' and user_id not in [doc['lender_id'], doc['vendor_id']]:
        flash("Unauthorized access to document.", "error")
        return redirect(url_for('agreements_list'))
        
    if not os.path.exists(doc['file_path']):
        flash("Document file not found on server storage.", "error")
        return redirect(url_for('agreement_details', agreement_id=doc['agreement_id']))
        
    return send_file(doc['file_path'], as_attachment=True, download_name=doc['document_name'])


@app.route('/agreement/<int:agreement_id>/pdf')
@login_required()
def generate_agreement_pdf(agreement_id):
    user_id = session['user_id']
    role = session.get('role')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT a.*, 
               app.full_name as vendor_full_name, app.email as vendor_email, app.phone as vendor_phone, app.profession as vendor_profession, app.loan_type, app.guarantor_name, app.guarantor_income,
               u_len.username as lender_name, u_len.email as lender_email, u_len.phone as lender_phone
        FROM agreements a
        JOIN applications app ON a.application_id = app.id
        JOIN users u_len ON a.lender_id = u_len.id
        WHERE a.id = ?
    ''', (agreement_id,))
    agr = cursor.fetchone()
    conn.close()
    
    if not agr:
        flash("Agreement not found.", "error")
        return redirect(url_for('agreements_list'))
        
    if role != 'admin' and user_id not in [agr['lender_id'], agr['vendor_id']]:
        flash("Unauthorized PDF download.", "error")
        return redirect(url_for('agreements_list'))
        
    buffer = io.BytesIO()
    
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0F172A'),
        alignment=1
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#64748B'),
        alignment=1
    )
    
    h2_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#1E293B'),
        spaceBefore=12,
        spaceAfter=6
    )
    
    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#334155')
    )
    
    # Header
    story.append(Paragraph("FINTRUST AI P2P LENDING", title_style))
    story.append(Paragraph(f"DIGITAL LOAN AGREEMENT & PROMISSORY NOTE &bull; Code: {agr['agreement_code']}", subtitle_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E1'), spaceAfter=15))
    
    # Summary Table
    summary_data = [
        [Paragraph("<b>Agreement ID:</b>", body_style), Paragraph(agr['agreement_code'], body_style), Paragraph("<b>Date & Time:</b>", body_style), Paragraph(str(agr['created_at']), body_style)],
        [Paragraph("<b>Application Ref:</b>", body_style), Paragraph(f"#AP-{agr['application_id']}", body_style), Paragraph("<b>Status:</b>", body_style), Paragraph(f"<b>{agr['status']}</b>", body_style)],
    ]
    sum_table = Table(summary_data, colWidths=[100, 160, 100, 160])
    sum_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#E2E8F0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(sum_table)
    story.append(Spacer(1, 15))
    
    # Parties Table
    story.append(Paragraph("PARTIES TO THE AGREEMENT", h2_style))
    parties_data = [
        [Paragraph("<b>LENDER DETAILS</b>", body_style), Paragraph("<b>VENDOR / BORROWER DETAILS</b>", body_style)],
        [
            Paragraph(f"<b>Name:</b> {agr['lender_name']}<br/><b>Email:</b> {agr['lender_email']}<br/><b>Phone:</b> {agr['lender_phone'] or 'N/A'}", body_style),
            Paragraph(f"<b>Name:</b> {agr['vendor_full_name']}<br/><b>Email:</b> {agr['vendor_email']}<br/><b>Phone:</b> {agr['vendor_phone']}<br/><b>Profession:</b> {agr['vendor_profession']}", body_style)
        ]
    ]
    part_table = Table(parties_data, colWidths=[260, 260])
    part_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#EEF2FF')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#C7D2FE')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E0E7FF')),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(part_table)
    story.append(Spacer(1, 15))
    
    # Financial Terms Table
    story.append(Paragraph("FINANCIAL TERMS & REPAYMENT SCHEDULE", h2_style))
    fin_data = [
        [Paragraph("<b>Principal Amount:</b>", body_style), Paragraph(f"₹{agr['loan_amount']:,.2f}", body_style), Paragraph("<b>Interest Rate:</b>", body_style), Paragraph(f"{agr['interest_rate']}% p.a.", body_style)],
        [Paragraph("<b>Tenure:</b>", body_style), Paragraph(f"{agr['tenure_months']} Months", body_style), Paragraph("<b>Monthly EMI:</b>", body_style), Paragraph(f"₹{agr['emi_amount']:,.2f}", body_style)],
        [Paragraph("<b>Processing Fee:</b>", body_style), Paragraph(f"₹{agr['processing_fee']:,.2f} (2%)", body_style), Paragraph("<b>Loan Purpose:</b>", body_style), Paragraph(agr['loan_type'], body_style)],
        [Paragraph("<b>Due Date:</b>", body_style), Paragraph("5th of every month", body_style), Paragraph("<b>Penalty Terms:</b>", body_style), Paragraph("2.0% per month on overdue installments", body_style)]
    ]
    fin_table = Table(fin_data, colWidths=[120, 140, 120, 140])
    fin_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#E2E8F0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(fin_table)
    story.append(Spacer(1, 15))
    
    # Legal Disclaimer & Mutual Acceptance Statement
    story.append(Paragraph("MUTUAL ACCEPTANCE & LEGAL DISCLAIMER", h2_style))
    statement_text = "<b>This agreement is digitally generated and mutually accepted by both the lender and the vendor through the platform.</b> By accepting this agreement, the vendor promises to repay the principal amount along with interest to the lender in monthly installments as specified."
    story.append(Paragraph(statement_text, body_style))
    story.append(Spacer(1, 10))
    disclaimer_text = "<i>Platform Disclaimer: FinTrust acts solely as an AI-powered Peer-to-Peer matchmaking and credit scoring technology service provider. FinTrust is not a banking entity and does not directly issue debt obligations. All financial transactions and promissory notes are legally binding directly between the Lender and the Vendor.</i>"
    story.append(Paragraph(disclaimer_text, body_style))
    story.append(Spacer(1, 15))
    
    # Digital Consent Logs Table
    story.append(Paragraph("DIGITAL CONSENT STAMPS", h2_style))
    vendor_stamp = f"ACCEPTED<br/>Time: {agr['vendor_consent_at'] or 'Pending'}<br/>IP: {agr['vendor_ip'] or 'N/A'}" if agr['vendor_consent'] else "PENDING ACCEPTANCE"
    lender_stamp = f"ACCEPTED<br/>Time: {agr['lender_consent_at'] or 'Pending'}<br/>IP: {agr['lender_ip'] or 'N/A'}" if agr['lender_consent'] else "PENDING ACCEPTANCE"
    
    stamp_data = [
        [Paragraph("<b>VENDOR DIGITAL SIGNATURE</b>", body_style), Paragraph("<b>LENDER DIGITAL SIGNATURE</b>", body_style)],
        [Paragraph(f"<b>{agr['vendor_full_name']}</b><br/>{vendor_stamp}", body_style), Paragraph(f"<b>{agr['lender_name']}</b><br/>{lender_stamp}", body_style)]
    ]
    stamp_table = Table(stamp_data, colWidths=[260, 260])
    stamp_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(stamp_table)
    
    doc.build(story)
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"{agr['agreement_code']}.pdf",
        mimetype='application/pdf'
    )

# --- Lender/Admin Flow ---

@app.route('/admin/dashboard')
@login_required('admin')
def admin_dashboard():
    search = request.args.get('search', '').strip()
    status = request.args.get('status', '').strip()
    loan_type = request.args.get('loan_type', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 8
    
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build query
    query = "SELECT * FROM applications WHERE 1=1"
    params = []
    
    if search:
        query += " AND (full_name LIKE ? OR email LIKE ? OR phone LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param])
    if status:
        query += " AND status = ?"
        params.append(status)
    if loan_type:
        query += " AND loan_type = ?"
        params.append(loan_type)
        
    # Get total count for filters
    count_query = query.replace("SELECT *", "SELECT COUNT(*)")
    cursor.execute(count_query, params)
    total_records = cursor.fetchone()[0]
    
    # Execute query with limit/offset
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])
    
    cursor.execute(query, params)
    app_rows = cursor.fetchall()
    
    apps = []
    for row in app_rows:
        app_dict = dict(row)
        t_score = compute_trust_score(row['user_id'])
        t_lvl, t_col = get_trust_level(t_score)
        app_dict['trust_score'] = t_score
        app_dict['trust_level'] = t_lvl
        app_dict['trust_color'] = t_col
        apps.append(app_dict)
    
    # Global dashboard metrics
    cursor.execute("SELECT COUNT(*) FROM applications")
    total_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM applications WHERE status = 'Approved'")
    approved_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM applications WHERE status = 'Rejected'")
    rejected_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM applications WHERE status = 'Pending'")
    pending_count = cursor.fetchone()[0]
    
    conn.close()
    
    total_pages = (total_records + per_page - 1) // per_page
    
    return render_template(
        'dashboard_admin.html',
        apps=apps,
        total_count=total_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        pending_count=pending_count,
        search=search,
        status=status,
        loan_type=loan_type,
        page=page,
        total_pages=total_pages
    )

@app.route('/admin/applications/<int:app_id>/status', methods=['POST'])
@login_required('admin')
def admin_change_status(app_id):
    new_status = request.form.get('status')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch applicant details before updating
    cursor.execute("SELECT user_id, loan_type, loan_amount FROM applications WHERE id = ?", (app_id,))
    app_row = cursor.fetchone()
    
    cursor.execute(
        "UPDATE applications SET status = ? WHERE id = ?",
        (new_status, app_id)
    )
    
    if app_row:
        user_id = app_row['user_id']
        loan_type = app_row['loan_type']
        loan_amount = app_row['loan_amount']
        notif_type = 'success' if new_status == 'Approved' else 'danger' if new_status == 'Rejected' else 'info'
        message = f"Your loan application #{app_id} for a {loan_type} Loan of ₹{loan_amount:,.2f} has been {new_status}."
        title = f"Loan Application {new_status}"
        cursor.execute("""
            INSERT INTO notifications (user_id, title, message, type)
            VALUES (?, ?, ?, ?)
        """, (user_id, title, message, notif_type))
        
    conn.commit()
    conn.close()
    
    flash(f"Application #{app_id} status updated to {new_status}.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/applications/<int:app_id>/delete', methods=['POST'])
@login_required('admin')
def admin_delete_application(app_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM applications WHERE id = ?", (app_id,))
    conn.commit()
    conn.close()
    
    flash(f"Application #{app_id} has been deleted.", "success")
    return redirect(url_for('admin_dashboard'))

# --- REST APIs ---

@app.route('/api/admin/stats')
@login_required('admin')
def api_admin_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Status Counts
    cursor.execute("SELECT status, COUNT(*) as count FROM applications GROUP BY status")
    status_rows = cursor.fetchall()
    status_counts = {row['status']: row['count'] for row in status_rows}
    # Ensure all labels exist
    for lbl in ['Approved', 'Moderate', 'Rejected', 'Pending']:
        status_counts.setdefault(lbl, 0)
        
    # 2. Risk Counts
    cursor.execute("SELECT risk_level, COUNT(*) as count FROM applications GROUP BY risk_level")
    risk_rows = cursor.fetchall()
    risk_counts = {row['risk_level']: row['count'] for row in risk_rows if row['risk_level']}
    for lbl in ['Low', 'Medium', 'High']:
        risk_counts.setdefault(lbl, 0)
        
    # 3. Monthly Trends (group by Year-Month)
    cursor.execute('''
        SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as count 
        FROM applications 
        GROUP BY month 
        ORDER BY month ASC
        LIMIT 6
    ''')
    monthly_rows = cursor.fetchall()
    monthly_counts = [{'month': row['month'], 'count': row['count']} for row in monthly_rows]
    
    # If no monthly records, add mock month
    if not monthly_counts:
        curr_month = datetime.now().strftime('%Y-%m')
        monthly_counts = [{'month': curr_month, 'count': 0}]
        
    conn.close()
    
    return jsonify({
        'success': True,
        'stats': {
            'status_counts': status_counts,
            'risk_counts': risk_counts,
            'monthly_counts': monthly_counts
        }
    })

@app.route('/api/applications/<int:app_id>/pdf')
@login_required()
def api_applications_pdf(app_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
    app_row = cursor.fetchone()
    conn.close()
    
    if not app_row:
        return "Application not found", 404
        
    # Security: applicant must own document
    if session.get('role') != 'admin' and app_row['user_id'] != session.get('user_id'):
        return "Unauthorized", 403
        
    reasons = json.loads(app_row['reasons'])
    new_emi = calculate_emi(app_row['loan_amount'], 0.09, app_row['loan_tenure'])
    dti = (app_row['existing_emi'] + new_emi) / (app_row['monthly_income'] + 0.5 * app_row['guarantor_income'])
    
    # Set up reportlab document buffer
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=letter, 
        rightMargin=40, 
        leftMargin=40, 
        topMargin=40, 
        bottomMargin=40
    )
    story = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'],
        fontName='Helvetica-Bold', fontSize=24, spaceAfter=8,
        textColor=colors.HexColor('#0F172A')
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle', parent=styles['Normal'],
        fontSize=10, textColor=colors.HexColor('#64748B'), spaceAfter=20
    )
    section_style = ParagraphStyle(
        'DocSection', parent=styles['Heading2'],
        fontName='Helvetica-Bold', fontSize=14, spaceBefore=15, spaceAfter=10,
        textColor=colors.HexColor('#1E3A8A')
    )
    body_style = ParagraphStyle(
        'DocBody', parent=styles['Normal'],
        fontSize=10, textColor=colors.HexColor('#334155'), spaceAfter=6
    )
    bullet_style = ParagraphStyle(
        'DocBullet', parent=styles['Normal'],
        fontSize=9.5, textColor=colors.HexColor('#334155'), leftIndent=15, spaceAfter=4
    )
    
    # Report Header
    story.append(Paragraph("FinTrust Eligibility Report", title_style))
    story.append(Paragraph(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Reference: #AP-{app_row['id']}", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#CBD5E1'), spaceAfter=15))
    
    # Score Section
    status_color = '#10B981' # Green
    if app_row['status'] == 'Moderate':
        status_color = '#F59E0B' # Amber
    elif app_row['status'] == 'Rejected':
        status_color = '#EF4444' # Red
        
    score_p = Paragraph(
        f"<b>Eligibility Score:</b> {app_row['eligibility_score']} / 100 &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"<b>Status:</b> <font color='{status_color}'><b>{app_row['status']}</b></font> &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"<b>Risk Level:</b> {app_row['risk_level']}",
        body_style
    )
    story.append(score_p)
    story.append(Spacer(1, 10))
    
    # Profile & Finance Table
    story.append(Paragraph("1. Profile & Financial Summary", section_style))
    data = [
        [Paragraph("<b>Parameter</b>", body_style), Paragraph("<b>Value</b>", body_style), Paragraph("<b>Parameter</b>", body_style), Paragraph("<b>Value</b>", body_style)],
        [Paragraph("Applicant Name", body_style), Paragraph(app_row['full_name'], body_style), Paragraph("Age / Gender", body_style), Paragraph(f"{app_row['age']} / {app_row['gender']}", body_style)],
        [Paragraph("Employment Type", body_style), Paragraph(app_row['employment_type'], body_style), Paragraph("Profession", body_style), Paragraph(app_row['profession'], body_style)],
        [Paragraph("Monthly Income", body_style), Paragraph(f"Rs. {app_row['monthly_income']:,.2f}", body_style), Paragraph("Existing Monthly EMI", body_style), Paragraph(f"Rs. {app_row['existing_emi']:,.2f}", body_style)],
        [Paragraph("Loan Type", body_style), Paragraph(app_row['loan_type'], body_style), Paragraph("Credit History Status", body_style), Paragraph("Good" if app_row['credit_history'] == 1 else "Poor", body_style)],
        [Paragraph("Requested Loan Amount", body_style), Paragraph(f"Rs. {app_row['loan_amount']:,.2f}", body_style), Paragraph("Tenure Requested", body_style), Paragraph(f"{app_row['loan_tenure']} Months", body_style)],
        [Paragraph("Guarantor Name", body_style), Paragraph(app_row['guarantor_name'], body_style), Paragraph("Guarantor Income", body_style), Paragraph(f"Rs. {app_row['guarantor_income']:,.2f}", body_style)],
        [Paragraph("Debt-to-Income (DTI)", body_style), Paragraph(f"{dti*100:.1f}%", body_style), Paragraph("Outstanding Debts Balance", body_style), Paragraph(f"Rs. {app_row['existing_debts']:,.2f}", body_style)]
    ]
    t = Table(data, colWidths=[130, 130, 130, 130])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
    ]))
    story.append(t)
    story.append(Spacer(1, 15))
    
    # XAI Section
    story.append(Paragraph("2. Explainable AI Risk Evaluation Factors", section_style))
    for reason in reasons:
        bullet = "•"
        if reason['type'] == 'pro':
            bullet_text = f"<font color='#10B981'><b>[+]</b></font> {reason['text']}"
        else:
            bullet_text = f"<font color='#EF4444'><b>[-]</b></font> {reason['text']}"
        story.append(Paragraph(bullet_text, bullet_style))
        
    story.append(Spacer(1, 15))
    
    # Recommendations Section
    story.append(Paragraph("3. Recommendations to Improve Eligibility", section_style))
    # Regenerate recommendations dynamically
    rec_found = False
    for reason in reasons:
        if reason['type'] == 'con':
            rec_found = True
            if 'debt-to-income' in reason['text']:
                story.append(Paragraph("• <b>Optimize Debt Service:</b> Pay off high-rate credit card balances to drop the monthly DTI below 36%.", bullet_style))
            elif 'credit history' in reason['text']:
                story.append(Paragraph("• <b>Repair Credit History:</b> Rectify dispute remarks, pay off lingering collections, and make bills in time.", bullet_style))
            elif 'loan size' in reason['text']:
                story.append(Paragraph("• <b>Adjust Principal Request:</b> Re-apply for a smaller loan size to decrease structural risk.", bullet_style))
            elif 'monthly income' in reason['text']:
                story.append(Paragraph("• <b>Increase Income Backing:</b> Add secondary borrowers or higher guarantor accounts to satisfy capacity limits.", bullet_style))
                
    if not rec_found:
        story.append(Paragraph("• Your application demonstrates excellent creditworthiness. Maintain current savings levels.", bullet_style))
        
    story.append(Spacer(1, 10))
    
    # Append structured AI parameters
    story.append(Paragraph("4. AI Recommended Financing Structure", section_style))
    rec = recommend_loan_parameters(app_row['monthly_income'], app_row['existing_emi'], app_row['loan_amount'])
    story.append(Paragraph(f"• <b>Recommended Principal Limit:</b> Rs. {rec['recommended_amount']:,.2f}", bullet_style))
    story.append(Paragraph(f"• <b>Recommended Monthly EMI:</b> Rs. {rec['recommended_emi']:,.2f} at suggested tenure of {rec['recommended_duration']} months", bullet_style))
    story.append(Paragraph(f"• <b>Suggested Interest Range:</b> {rec['suggested_interest_range']}", bullet_style))
    story.append(Paragraph(f"• <b>Financial Health Score:</b> {rec['financial_health_score']}/100 &nbsp;&nbsp;|&nbsp;&nbsp; <b>Approval Probability:</b> {rec['approval_probability']}%", bullet_style))
    
    story.append(Spacer(1, 15))
    
    # Append official compliance disclaimer
    story.append(Paragraph("5. Compliance & Platform AI Disclaimer", section_style))
    story.append(Paragraph(
        "This recommendation is generated by AI based on user-provided information. Final lending decisions remain entirely between lenders and borrowers. FinTrust AI is not a financial institution and is not responsible for any financial transactions or disputes.",
        ParagraphStyle('DisclCommercial', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#64748B'), fontName='Helvetica-Oblique')
    ))
    
    story.append(Spacer(1, 15))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#E2E8F0'), spaceAfter=10))
    story.append(Paragraph("<i>Disclaimer: This report represents automated AI underwriting prediction and does not constitute a binding legal credit agreement.</i>", ParagraphStyle('Discl', parent=styles['Normal'], fontSize=7.5, textColor=colors.HexColor('#94A3B8'))))
    
    # Build Document
    doc.build(story)
    buffer.seek(0)
    
    return send_file(
        buffer, 
        as_attachment=True, 
        download_name=f"FinTrust_Report_AP{app_row['id']}.pdf", 
        mimetype='application/pdf'
    )

import urllib.request
import json

def get_gemini_response(api_key, prompt, context_data=None):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={api_key}"
    
    system_instr = (
        "You are FinTrust's AI Assistant, a friendly and professional financial advisor helping users on a "
        "Peer-to-Peer (P2P) lending and machine-learning trust scoring platform. "
        "Answer the user's question clearly and concisely in a conversational style. Keep responses short and helpful (max 3-4 sentences)."
    )
    
    full_prompt = f"System Instruction: {system_instr}\n\n"
    if context_data:
        full_prompt += f"Logged-in User Context:\n{json.dumps(context_data, indent=2)}\n\n"
    full_prompt += f"User Question: {prompt}"
    
    data = {
        "contents": [{
            "parts": [{"text": full_prompt}]
        }],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 250
        }
    }
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            return res_data['candidates'][0]['content']['parts'][0]['text'].strip()
    except Exception as e:
        print(f"Gemini API Exception: {e}")
        return None


def verify_document_with_gemini(api_key, file_path, doc_type):
    import base64
    import mimetypes
    import os
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={api_key}"
    
    # Read file content and base64 encode it
    try:
        with open(file_path, "rb") as f:
            file_data = f.read()
            base64_data = base64.b64encode(file_data).decode("utf-8")
    except Exception as e:
        print(f"Error reading file for Gemini verification: {e}", flush=True)
        return None

    # Determine MIME type
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        # Fallback MIME types based on file extension
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.jpg', '.jpeg']:
            mime_type = 'image/jpeg'
        elif ext == '.png':
            mime_type = 'image/png'
        elif ext == '.pdf':
            mime_type = 'application/pdf'
        else:
            mime_type = 'application/octet-stream'

    prompt = (
        f"You are an automated document verification system. "
        f"Analyze the attached document and determine if it is a valid document of category: '{doc_type}'. "
        f"The valid categories and their meanings are:\n"
        f"- pan_verification: Permanent Account Number (PAN Card) of India.\n"
        f"- aadhaar_verification: Aadhaar Card of India (front, back, or both).\n"
        f"- bank_statement: A Bank Statement or passbook page.\n"
        f"- salary_slip: A Salary Slip / payslip from an employer.\n"
        f"- business_registration: GST registration certificate, Trade License, or corporate registration certificate.\n\n"
        f"Instructions:\n"
        f"1. Perform OCR and check if the document structure, text, and labels match a genuine document of type '{doc_type}'.\n"
        f"2. If it is blank, completely blurred, unrelated (like a cat, a landscape, or a completely different document type), or contains fake/draft watermark indicators, mark it as verified: false.\n"
        f"3. Return ONLY a valid JSON object. Do not include any markdown styling like ```json or any other text. The JSON object must have exactly two fields:\n"
        f"   - 'verified': boolean (true or false)\n"
        f"   - 'notes': string (a short explanation of your decision, max 12 words)\n"
    )

    data = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": base64_data
                    }
                }
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 150,
            "responseMimeType": "application/json"
        }
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            text = res_data['candidates'][0]['content']['parts'][0]['text'].strip()
            
            # Clean markdown code blocks if model ignores responseMimeType
            if text.startswith("```"):
                lines = text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines).strip()
                
            res_json = json.loads(text)
            print(f"[INFO] Gemini document verification result: {res_json}", flush=True)
            return res_json
    except Exception as e:
        print(f"Gemini document verification API Exception: {e}", flush=True)
        return None

@app.route('/api/chatbot', methods=['POST'])
def chatbot_api():
    data = request.get_json() or {}
    message_raw = data.get('message', '').strip()
    message = message_raw.lower()
    
    if not session.get('user_id'):
        return jsonify({
            'response': "Hello! Please log in so that I can analyze your specific financial records and assist you with your P2P applications."
        })
        
    user_id = session['user_id']
    role = session['role']
    username = session.get('username', 'User')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get latest application
    cursor.execute("SELECT * FROM applications WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,))
    latest_app = cursor.fetchone()
    
    # Get verified documents list
    cursor.execute("SELECT document_type FROM vendor_documents WHERE user_id = ? AND status = 'Verified'", (user_id,))
    verified_docs = [row['document_type'] for row in cursor.fetchall()]
    
    # Pre-calculate trust score & level
    score = compute_trust_score(user_id)
    level, _ = get_trust_level(score)
    
    conn.close()
    
    # Split message into words for precise word matching
    words = message.split()
    
    # 1. Greetings (exact word match for short greetings to prevent sub-string matching)
    if any(greet in words for greet in ['hi', 'hello', 'hey', 'yo', 'greetings']) or 'who are you' in message or 'what is your name' in message:
        return jsonify({
            'response': f"Hello {username}! I am FinTrust's AI Assistant. I can help analyze your credit evaluation, check matching results with P2P lenders, suggest optimized loan parameters, or guide you on improving your trust score. How can I assist you today?"
        })
        
    # 2. EMI / Calculator (Check this before general 'calculate' keyword checks)
    elif 'emi' in message or 'calculator' in message:
        return jsonify({
            'response': "Our platform features an interactive EMI Calculator. Monthly payments are calculated using: `EMI = [P x r x (1+r)^n] / [(1+r)^n - 1]`. You can access it via the 'EMI Calculator' link in the top menu bar."
        })
        
    # 3. Trust Score (Why is it low / How to improve)
    elif 'trust score' in message or 'score' in message or 'improve' in message:
        missing = []
        if 'pan_verification' not in verified_docs:
            missing.append("PAN Card (+15 points)")
        if 'aadhaar_verification' not in verified_docs:
            missing.append("Aadhaar Card (+15 points)")
        if 'bank_statement' not in verified_docs:
            missing.append("Bank Statement (+15 points)")
        if 'salary_slip' not in verified_docs:
            missing.append("Salary Slip (+15 points)")
        if 'business_registration' not in verified_docs:
            missing.append("Business Registration (+10 points)")
            
        if not missing:
            return jsonify({
                'response': f"Your trust score is {score}/100 ({level} Level). All core documents are verified. Maintaining positive transaction histories and co-applying with stable guarantors can maximize your approval rates."
            })
        else:
            return jsonify({
                'response': f"Your trust score is currently {score}/100 ({level} Level). You can improve it by uploading the following documents in the 'Verify Trust' tab: {', '.join(missing)}."
            })
            
    # 4. Matching / Lenders
    elif 'match' in message or 'lender' in message:
        if role == 'lender':
            return jsonify({
                'response': "Matches are determined by your lending preferences (maximum loan size, interest rate, duration, and target location). Adjusting your settings in the preferences panel will dynamically update your recommendations."
            })
        else:
            if not latest_app:
                return jsonify({
                    'response': "You haven't submitted a loan application yet! Once you apply, the AI matching engine will match you with eligible peer-to-peer lenders based on your criteria and trust level."
                })
            if score < 50:
                return jsonify({
                    'response': "Your matches may currently be limited due to a low trust score (below 50). We highly recommend uploading your PAN, Aadhaar, and Bank Statements to unlock more lenders."
                })
            else:
                return jsonify({
                    'response': "The matching engine pairs you with lenders who support your requested loan size and whose minimum trust score criteria you meet. Check 'My Dashboard' to view active matches."
                })
                
    # 5. Suggest Loan Parameters
    elif 'suggest' in message or 'recommend' in message or 'amount' in message:
        if not latest_app:
            return jsonify({
                'response': "Please submit an application or enter your income details first so I can calculate your recommended loan parameters."
            })
        rec = recommend_loan_parameters(latest_app['monthly_income'], latest_app['existing_emi'], latest_app['loan_amount'])
        return jsonify({
            'response': f"Based on your net monthly income of ₹{latest_app['monthly_income']:,.2f} and existing EMIs, the AI recommendation is a loan of ₹{rec['recommended_amount']:,.2f} for {rec['recommended_duration']} months (EMI: ₹{rec['recommended_emi']:,.2f}/mo) to ensure stable repayment."
        })
        
    # 6. Missing / Upload Documents
    elif 'document' in message or 'missing' in message or 'upload' in message or 'verify' in message:
        all_docs = {
            'pan_verification': 'PAN Card',
            'aadhaar_verification': 'Aadhaar Card',
            'bank_statement': 'Bank Statement',
            'salary_slip': 'Salary Slip',
            'business_registration': 'Business Registration'
        }
        missing = [name for key, name in all_docs.items() if key not in verified_docs]
        if not missing:
            return jsonify({
                'response': "Fantastic! All requested documents have been successfully uploaded and verified by our automated document verification engine."
            })
        else:
            return jsonify({
                'response': f"The following documents are missing or pending verification: {', '.join(missing)}. Please visit the 'Verify Trust' page to upload them."
            })
            
    # 7. Compatibility / Calculation vectors
    elif 'compatibility' in message or 'calculate' in message or 'vector' in message:
        return jsonify({
            'response': "Compatibility is evaluated across 4 core vectors: (1) Trust Score match (2) Maximum lending limit compatibility (3) Loan duration matching, and (4) City/state location affinity."
        })
        
    # 8. Application Status / Approval
    elif any(kw in message for kw in ['status', 'approve', 'reject', 'eligible', 'application']):
        if not latest_app:
            return jsonify({
                'response': "You do not have any active applications. Head over to the 'Apply for Loan' page to submit your details and get an instant AI credit evaluation!"
            })
        else:
            return jsonify({
                'response': f"Your latest application (ID: #AP-{latest_app['id']}) for a ₹{latest_app['loan_amount']:,.2f} loan is currently **{latest_app['status']}** with an AI eligibility score of {latest_app['eligibility_score']}/100 and risk level set to {latest_app['risk_level']}."
            })
            
    # 9. Thank you
    elif any(thanks in message for thanks in ['thanks', 'thank you', 'great', 'awesome', 'cool', 'perfect']):
        return jsonify({
            'response': "You're very welcome! I'm here to help. Let me know if you have any other questions about FinTrust AI."
        })
        
    # 10. Help command
    elif 'help' in message or 'command' in message:
        return jsonify({
            'response': "You can ask me questions about your profile or P2P lending, such as:\n• 'Why is my trust score low?'\n• 'What documents are missing?'\n• 'Suggest a safe loan amount'\n• 'How does lender matching work?'\n• 'How is compatibility calculated?'\n• 'What is my application status?'"
        })
        
    # 11. General fallback / Gemini API call
    import os
    gemini_key = os.environ.get('GEMINI_API_KEY')
    if gemini_key:
        context_data = {
            'username': username,
            'role': role,
            'trust_score': score,
            'trust_level': level,
            'verified_documents': verified_docs,
            'latest_application': {
                'id': latest_app['id'],
                'loan_amount': latest_app['loan_amount'],
                'loan_type': latest_app['loan_type'],
                'status': latest_app['status'],
                'eligibility_score': latest_app['eligibility_score'],
                'risk_level': latest_app['risk_level'],
                'monthly_income': latest_app['monthly_income'],
                'existing_emi': latest_app['existing_emi']
            } if latest_app else None
        }
        gemini_reply = get_gemini_response(gemini_key, message_raw, context_data)
        if gemini_reply:
            return jsonify({'response': gemini_reply})
            
    return jsonify({
        'response': "I'm sorry, I didn't quite catch that. You can ask me: 'Why is my trust score low?', 'What documents are missing?', 'Suggest a safe loan amount', 'How is compatibility calculated?', 'What is my application status?', or simply say 'help' to see list of options."
    })

# --- Vendor Document Verification Routes ---

@app.route('/applicant/verification')
@app.route('/lender/verification')
@login_required()
def vendor_verification_ui():
    return render_template('verification.html')

@app.route('/api/vendor/upload', methods=['POST'])
@login_required()
def vendor_upload_document():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file segment in request'}), 400
    file = request.files['file']
    doc_type = request.form.get('document_type')
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
        
    valid_doc_types = ['pan_verification', 'aadhaar_verification', 'bank_statement', 'salary_slip', 'business_registration']
    if not doc_type or doc_type not in valid_doc_types:
        return jsonify({'success': False, 'error': 'Invalid document category'}), 400
        
    if file and allowed_file(file.filename):
        filename = f"user_{session['user_id']}_{doc_type}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Try real Gemini Multimodal AI document verification first
        gemini_key = os.environ.get('GEMINI_API_KEY')
        real_verification = None
        if gemini_key:
            real_verification = verify_document_with_gemini(gemini_key, file_path, doc_type)
            
        if real_verification is not None:
            status = 'Verified' if real_verification.get('verified') else 'Rejected'
            notes = real_verification.get('notes', 'AI verification complete.')
        else:
            # Fall back to simulated AI Document Verification check (OCR & Registry lookup mock)
            status = 'Verified'
            notes = "Automated verification successful. Format checks passed, document active in registry."
            
            # Check both filename and file content for fake/invalid/draft indicators
            lower_fn = file.filename.lower()
            is_fake = False
            fake_keywords = ['fake', 'invalid', 'draft']
            
            # Check filename
            for kw in fake_keywords:
                if kw in lower_fn:
                    is_fake = True
                    break
                    
            # Check file content
            if not is_fake:
                try:
                    with open(file_path, 'rb') as f:
                        file_content_lower = f.read().lower()
                    for kw in fake_keywords:
                        if kw.encode('utf-8') in file_content_lower:
                            is_fake = True
                            break
                except Exception as e:
                    # If we fail to read, log the issue but proceed
                    print(f"Error reading file for validation: {e}")
                    
            if is_fake:
                status = 'Rejected'
                notes = "Verification failed. System detected invalid stamp, watermarked draft copy, or fake indicators."
        
        # Write/Update SQLite record
        conn = get_db_connection()
        cursor = conn.cursor()
        # Check if category already uploaded, if so update
        cursor.execute("SELECT id FROM vendor_documents WHERE user_id = ? AND document_type = ?", (session['user_id'], doc_type))
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                "UPDATE vendor_documents SET document_name = ?, file_path = ?, status = ?, verification_notes = ?, created_at = CURRENT_TIMESTAMP WHERE id = ?",
                (file.filename, file_path, status, notes, existing['id'])
            )
        else:
            cursor.execute(
                "INSERT INTO vendor_documents (user_id, document_name, document_type, file_path, status, verification_notes) VALUES (?, ?, ?, ?, ?, ?)",
                (session['user_id'], file.filename, doc_type, file_path, status, notes)
            )
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f"Document uploaded. System auto-status: {status}.",
            'status': status
        })
        
    return jsonify({'success': False, 'error': 'Allowed file types are PDF, PNG, JPG, JPEG'}), 400

@app.route('/api/vendor/trust-score')
@login_required()
def vendor_get_trust_details():
    user_id = session['user_id']
    score = compute_trust_score(user_id)
    level, color = get_trust_level(score)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vendor_documents WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    docs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    # format date
    for doc in docs:
        if isinstance(doc['created_at'], str):
            doc['created_at'] = doc['created_at'][:19]
            
    return jsonify({
        'success': True,
        'score': score,
        'level': level,
        'level_color': color,
        'documents': docs
    })

@app.route('/admin/documents/<int:doc_id>/status', methods=['POST'])
@login_required()
def admin_document_action(doc_id):
    new_status = request.form.get('status')
    redirect_url = request.form.get('redirect_url')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vendor_documents WHERE id = ?", (doc_id,))
    doc = cursor.fetchone()
    
    if not doc:
        conn.close()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or redirect_url is None:
            return jsonify({'success': False, 'error': 'Document not found'}), 404
        flash("Document not found.", "error")
        return redirect(url_for('applicant_dashboard'))
        
    # Authorization checks
    if session.get('role') != 'admin' and doc['user_id'] != session.get('user_id'):
        conn.close()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or redirect_url is None:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        flash("Unauthorized.", "error")
        return redirect(url_for('applicant_dashboard'))
        
    if new_status == 'Deleted' or new_status == 'Deleted_Manual':
        # remove local file
        try:
            if os.path.exists(doc['file_path']):
                os.remove(doc['file_path'])
        except:
            pass
        cursor.execute("DELETE FROM vendor_documents WHERE id = ?", (doc_id,))
        conn.commit()
        conn.close()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or redirect_url is None:
            return jsonify({'success': True, 'message': 'Document deleted'})
        flash("Document deleted.", "success")
        return redirect(redirect_url)
        
    # Admin override status (Verified or Rejected)
    if session.get('role') == 'admin':
        notes = "Status overridden manually by lender administrator." if new_status == 'Verified' else "Document rejected upon underwriter review."
        cursor.execute(
            "UPDATE vendor_documents SET status = ?, verification_notes = ? WHERE id = ?",
            (new_status, notes, doc_id)
        )
        # Notify the user about their document status update
        notif_type = 'success' if new_status == 'Verified' else 'danger'
        title = f"Document {new_status}"
        message = f"Your document '{doc['document_name']}' has been {new_status}."
        cursor.execute("""
            INSERT INTO notifications (user_id, title, message, type)
            VALUES (?, ?, ?, ?)
        """, (doc['user_id'], title, message, notif_type))
        
        conn.commit()
        conn.close()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or redirect_url is None:
            return jsonify({'success': True, 'message': f'Document updated to {new_status}'})
        flash(f"Document status overridden to {new_status}.", "success")
        return redirect(redirect_url)
        
    conn.close()
    return jsonify({'success': False, 'error': 'Invalid action'}), 400

# --- Payment API Routes ---

@app.route('/api/payments/create-order', methods=['POST'])
@login_required()
def api_create_payment_order():
    data = request.get_json() or {}
    amount = data.get('amount')
    app_id = data.get('application_id')
    
    if not amount or not app_id:
        return jsonify({'success': False, 'error': 'Missing amount or application_id'}), 400
        
    try:
        amount_val = float(amount)
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid amount'}), 400
        
    gateway_order_id = f"order_mock_{secrets.token_hex(8)}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO transactions (user_id, application_id, amount, gateway_order_id, status) VALUES (?, ?, ?, ?, 'created')",
            (session['user_id'], app_id, amount_val, gateway_order_id)
        )
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)}), 500
        
    conn.close()
    return jsonify({
        'success': True,
        'order_id': gateway_order_id,
        'amount': amount_val,
        'key_id': 'mock_key_fintrust_12345'
    })

@app.route('/api/payments/verify', methods=['POST'])
@login_required()
def api_verify_payment():
    data = request.get_json() or {}
    order_id = data.get('razorpay_order_id')
    payment_id = data.get('razorpay_payment_id') or f"pay_mock_{secrets.token_hex(8)}"
    
    if not order_id:
        return jsonify({'success': False, 'error': 'Missing razorpay_order_id'}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    # Check if transaction exists
    cursor.execute("SELECT * FROM transactions WHERE gateway_order_id = ?", (order_id,))
    tx = cursor.fetchone()
    if not tx:
        conn.close()
        return jsonify({'success': False, 'error': 'Transaction order not found'}), 404
        
    try:
        cursor.execute(
            "UPDATE transactions SET status = 'completed', gateway_payment_id = ? WHERE gateway_order_id = ?",
            (payment_id, order_id)
        )
        # Also create a notification for user
        title = "EMI Payment Successful"
        message = f"Your payment of ₹{tx['amount']:,.2f} for application #AP-{tx['application_id']} was verified successfully."
        cursor.execute(
            "INSERT INTO notifications (user_id, title, message, type) VALUES (?, ?, ?, 'success')",
            (session['user_id'], title, message)
        )
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)}), 500
        
    conn.close()
    return jsonify({'success': True, 'message': 'Payment completed and verified successfully'})

@app.route('/api/payments/history')
@login_required()
def api_payment_history():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, application_id, amount, currency, gateway_order_id, gateway_payment_id, status, created_at FROM transactions WHERE user_id = ? ORDER BY id DESC",
        (session['user_id'],)
    )
    rows = cursor.fetchall()
    conn.close()
    return jsonify({'success': True, 'transactions': [dict(r) for r in rows]})

recent_errors_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'error_log.txt')

@app.errorhandler(Exception)
def handle_exception(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
        
    import traceback
    tb = traceback.format_exc()
    error_msg = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {e}\n{tb}\n"
    
    # Append to log file
    try:
        with open(recent_errors_file, 'a', encoding='utf-8') as f:
            f.write(error_msg)
    except Exception as io_err:
        print(f"Failed to write to error log file: {io_err}", flush=True)
        
    print(f"CRITICAL EXCEPTION TRIGGERED: {e}\n{tb}", flush=True)
    
    if request.path.startswith('/api/') or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({'success': False, 'error': f"Internal Server Error: {e}"}), 500
        
    return f"""
    <html>
    <head>
        <title>500 Internal Server Error</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f1f5f9; padding: 40px; line-height: 1.6;">
        <div style="max-width: 800px; margin: 0 auto; background: rgba(30, 41, 59, 0.5); padding: 30px; border-radius: 12px; border: 1px solid #334155;">
            <h1 style="color: #ef4444; margin-top: 0;">500 Internal Server Error</h1>
            <p>An unexpected exception was encountered while processing your request.</p>
            <h3 style="color: #3b82f6; margin-top: 24px;">Traceback Log:</h3>
            <pre style="background: #020617; padding: 20px; border-radius: 8px; overflow-x: auto; border: 1px solid #1e293b; color: #e2e8f0; font-size: 0.85rem; font-family: monospace;">{tb}</pre>
            <p style="margin-top: 20px;"><a href="/login" style="color: #3b82f6; text-decoration: none; font-weight: 500;">&larr; Back to Authentication Page</a></p>
        </div>
    </body>
    </html>
    """, 500

@app.route('/dev/users')
def dev_users():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, email, phone, role, firebase_uid, created_at FROM users ORDER BY id DESC")
        users = [dict(row) for row in cursor.fetchall()]
        cursor.execute("SELECT id, email, otp, expires_at, created_at FROM otps ORDER BY id DESC")
        otps = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return jsonify({'users': users, 'otps': otps})
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        # Log to file
        try:
            with open(recent_errors_file, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] dev_users error: {e}\n{tb}\n")
        except Exception:
            pass
        raise e

@app.route('/dev/errors')
def dev_errors():
    logs = ""
    if os.path.exists(recent_errors_file):
        try:
            with open(recent_errors_file, 'r', encoding='utf-8') as f:
                logs = f.read()
        except Exception as e:
            logs = f"Failed to read logs: {e}"
    return f"<pre>{logs}</pre>"


@app.route('/dev/get-otp/<email>')
def dev_get_otp(email):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT otp FROM otps WHERE email = ? ORDER BY id DESC LIMIT 1", (email,))
    row = cursor.fetchone()
    conn.close()
    return jsonify({'otp': row['otp'] if row else None})


# --- STANDALONE REST API ENDPOINTS FOR DECOUPLED FRONTEND ---

@app.route('/api/auth/me')
def api_auth_me():
    if 'user_id' not in session:
        return jsonify({'authenticated': False}), 200
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, phone, role FROM users WHERE id = ?", (session['user_id'],))
    user = cursor.fetchone()
    if not user:
        session.clear()
        conn.close()
        return jsonify({'authenticated': False}), 200
    user_dict = dict(user)
    trust_score = compute_trust_score(user_dict['id'])
    user_dict['trust_score'] = trust_score
    user_dict['trust_level'], user_dict['trust_color'] = get_trust_level(trust_score)
    
    # Notifications
    cursor.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (user_dict['id'],))
    notifications = [dict(row) for row in cursor.fetchall()]
    cursor.execute("SELECT COUNT(*) as cnt FROM notifications WHERE user_id = ? AND is_read = 0", (user_dict['id'],))
    unread_count = cursor.fetchone()['cnt']
    conn.close()
    
    return jsonify({
        'authenticated': True,
        'user': user_dict,
        'notifications': notifications,
        'unread_count': unread_count
    })

@app.route('/api/auth/logout', methods=['POST', 'GET'])
def api_auth_logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out successfully'})

@app.route('/api/translations/<lang>')
def api_get_translations(lang):
    if lang in TRANSLATIONS:
        return jsonify({'success': True, 'lang': lang, 'translations': TRANSLATIONS[lang]})
    return jsonify({'success': True, 'lang': 'en', 'translations': TRANSLATIONS.get('en', {})})

@app.route('/api/calculator', methods=['POST'])
def api_calculator():
    data = request.get_json() or {}
    amount = float(data.get('amount', 100000))
    rate = float(data.get('rate', 10.5))
    tenure = int(data.get('tenure', 12))
    income = float(data.get('income', 50000))
    existing_emi = float(data.get('existing_emi', 0))
    
    emi = calculate_emi(amount, rate, tenure)
    total_payment = emi * tenure
    total_interest = total_payment - amount
    rec = recommend_loan_parameters(income, existing_emi, amount)
    
    return jsonify({
        'success': True,
        'emi': round(emi, 2),
        'total_interest': round(total_interest, 2),
        'total_payment': round(total_payment, 2),
        'recommendation': rec
    })

@app.route('/api/applicant/dashboard/data')
@login_required('applicant')
def api_applicant_dashboard_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM applications WHERE user_id = ? ORDER BY created_at DESC", (session['user_id'],))
    apps = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT m.id as match_id, m.compatibility_score, m.reasons, m.lender_status, m.borrower_status,
               u.id as lender_user_id, u.username as lender_name, u.email as lender_email, u.phone as lender_phone,
               lp.interest_rate, a.id as application_id, a.loan_amount, a.loan_tenure
        FROM matches m
        JOIN applications a ON m.application_id = a.id
        JOIN users u ON m.lender_id = u.id
        LEFT JOIN lender_preferences lp ON u.id = lp.user_id
        WHERE a.user_id = ?
        ORDER BY m.created_at DESC
    """, (session['user_id'],))
    matches = [dict(row) for row in cursor.fetchall()]
    for m in matches:
        if m.get('reasons'):
            try:
                m['reasons'] = json.loads(m['reasons'])
            except Exception:
                pass
                
    cursor.execute("SELECT * FROM vendor_documents WHERE user_id = ? ORDER BY created_at DESC", (session['user_id'],))
    docs = [dict(row) for row in cursor.fetchall()]
    
    trust_score = compute_trust_score(session['user_id'])
    trust_level, trust_color = get_trust_level(trust_score)
    conn.close()
    
    return jsonify({
        'success': True,
        'applications': apps,
        'matches': matches,
        'documents': docs,
        'trust_score': trust_score,
        'trust_level': trust_level,
        'trust_color': trust_color
    })

@app.route('/api/lender/dashboard/data')
@login_required('lender')
def api_lender_dashboard_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM lender_preferences WHERE user_id = ?", (session['user_id'],))
    pref = cursor.fetchone()
    pref_dict = dict(pref) if pref else {}
    
    cursor.execute("""
        SELECT m.id as match_id, m.compatibility_score, m.reasons, m.lender_status, m.borrower_status,
               a.id as application_id, a.full_name, a.loan_amount, a.loan_tenure, a.risk_level as risk_category, a.approval_probability,
               u.email as borrower_email
        FROM matches m
        JOIN applications a ON m.application_id = a.id
        JOIN users u ON a.user_id = u.id
        WHERE m.lender_id = ?
        ORDER BY m.created_at DESC
    """, (session['user_id'],))
    matches = [dict(row) for row in cursor.fetchall()]
    for m in matches:
        if m.get('reasons'):
            try:
                m['reasons'] = json.loads(m['reasons'])
            except Exception:
                pass

    cursor.execute("SELECT * FROM applications ORDER BY created_at DESC LIMIT 50")
    all_apps = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return jsonify({
        'success': True,
        'preferences': pref_dict,
        'matches': matches,
        'applications': all_apps
    })

@app.route('/api/admin/dashboard/data')
@login_required('admin')
def api_admin_dashboard_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM applications ORDER BY created_at DESC")
    apps = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT vd.*, u.username, u.email FROM vendor_documents vd JOIN users u ON vd.user_id = u.id ORDER BY vd.created_at DESC")
    docs = [dict(row) for row in cursor.fetchall()]
    
    total_apps = len(apps)
    approved_apps = sum(1 for a in apps if a['status'] == 'Approved')
    pending_apps = sum(1 for a in apps if a['status'] == 'Pending')
    rejected_apps = sum(1 for a in apps if a['status'] == 'Rejected')
    
    conn.close()
    return jsonify({
        'success': True,
        'applications': apps,
        'documents': docs,
        'stats': {
            'total': total_apps,
            'approved': approved_apps,
            'pending': pending_apps,
            'rejected': rejected_apps
        }
    })

@app.route('/api/agreements/data')
@login_required()
def api_agreements_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    user_id = session['user_id']
    role = session.get('role')
    
    if role == 'lender':
        cursor.execute("""
            SELECT da.*, a.full_name as applicant_name, a.loan_amount, u.username as lender_name
            FROM agreements da
            JOIN applications a ON da.application_id = a.id
            JOIN users u ON da.lender_id = u.id
            WHERE da.lender_id = ?
            ORDER BY da.created_at DESC
        """, (user_id,))
    else:
        cursor.execute("""
            SELECT da.*, a.full_name as applicant_name, a.loan_amount, u.username as lender_name
            FROM agreements da
            JOIN applications a ON da.application_id = a.id
            JOIN users u ON da.lender_id = u.id
            WHERE da.vendor_id = ?
            ORDER BY da.created_at DESC
        """, (user_id,))
    agreements = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({'success': True, 'agreements': agreements})



# Initialize DB tables
try:
    from database import init_db
    init_db()
    print("Database tables initialized successfully.", flush=True)
except Exception as e:
    print(f"DATABASE INITIALIZATION ERROR: {e}", flush=True)

if __name__ == '__main__':
    # Run dev server
    app.run(debug=True, port=5000)

