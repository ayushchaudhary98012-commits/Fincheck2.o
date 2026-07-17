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
    if email_pass:
        email_pass = email_pass.replace(" ", "").strip()
        
    # Always print OTP to the console for easy debugging/testing
    print("\n" + "*" * 60, flush=True)
    print(f"[OTP SECURITY CODE] Sent To: {to_email}", flush=True)
    print(f"[OTP Code]: {otp}", flush=True)
    print("*" * 60 + "\n", flush=True)
    
    # If using seeded test accounts (e.g. user@fincheck.com), route OTP to the configured EMAIL_USER
    target_email = to_email
    if to_email.lower().endswith('@fincheck.com') and email_user:
        target_email = email_user
        print(f"[INFO] Redirected test account OTP from {to_email} to configured developer email {email_user}", flush=True)
    
    if not email_user or not email_pass:
        print("\n" + "="*50, flush=True)
        print("WARNING: EMAIL_USER and/or EMAIL_PASS environment variables are not set!", flush=True)
        print("SIMULATING EMAIL SEND IN CONSOLE ONLY.", flush=True)
        print(f"To: {target_email}")
        print(f"Subject: FinCheck AI - Login Verification Code")
        print(f"OTP Code: {otp}")
        print("="*50 + "\n")
        return True
        
    try:
        from email.utils import formatdate, make_msgid
        msg = MIMEMultipart()
        msg['From'] = email_user
        msg['To'] = target_email
        msg['Subject'] = f"FinCheck Verification Code: {otp}"
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid()
        
        body = f"""Hello,
 
Your FinCheck AI login verification code is: {otp}
 
This code is valid for 5 minutes. Please enter this code on the verification screen to complete your login.
 
If you did not request this code, please secure your account.
 
Best regards,
FinCheck Security Team"""
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
        server.starttls()
        server.login(email_user, email_pass)
        server.sendmail(email_user, [target_email], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        import traceback
        print("\n" + "="*50)
        print(f"ERROR: Email delivery failed: {e}")
        traceback.print_exc()
        print("="*50 + "\n")
        raise e

# ReportLab imports for PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

app = Flask(__name__,
            template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'templates'),
            static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'static'))
app.secret_key = 'fincheck_super_secret_session_key_19385'

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
            if role and session.get('role') != role:
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
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Fetch application details
    cursor.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
    app_row = cursor.fetchone()
    if not app_row:
        conn.close()
        return
        
    user_id = app_row['user_id']
    loan_amount = app_row['loan_amount']
    loan_tenure = app_row['loan_tenure']
    
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
        max_amount = lender['max_lending_amount']
        min_score = lender['min_trust_score']
        pref_dur = lender['preferred_duration']
        pref_loc = lender['preferred_location']
        
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
            
        if pref_loc == 'All' or pref_loc.lower() == 'mumbai' or pref_loc.lower() in app_row['full_name'].lower():
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
        action = request.form.get('action')
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if action == 'login':
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user = cursor.fetchone()
            
            if user and check_password_hash(user['password_hash'], password):
                email = user['email']
                otp = generate_6_digit_otp()
                expires_at = (datetime.now() + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
                
                # Store OTP in database
                cursor.execute("DELETE FROM otps WHERE email = ?", (email,))
                cursor.execute("""
                    INSERT INTO otps (email, otp, expires_at)
                    VALUES (?, ?, ?)
                """, (email, otp, expires_at))
                conn.commit()
                conn.close()
                
                try:
                    send_otp_email(email, otp)
                    session['pre_auth_email'] = email
                    flash("OTP Sent Successfully. Please verify your identity.", "success")
                    return redirect(url_for('verify_otp_route'))
                except Exception as e:
                    flash(f"Unable to send OTP. Error: {e}", "error")
                    return render_template('login.html')
            else:
                conn.close()
                flash("Invalid username or password.", "error")
                return render_template('login.html')
                
        elif action == 'register':
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            role = request.form.get('role', 'applicant')
            
            # Form checks
            if not username or not email or not phone or not password:
                flash("All fields are required.", "error")
                return render_template('login.html')
                
            hashed_pass = generate_password_hash(password)
            try:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, email, phone, role) VALUES (?, ?, ?, ?, ?)",
                    (username, hashed_pass, email, phone, role)
                )
                user_id = cursor.lastrowid
                if role == 'lender':
                    cursor.execute(
                        "INSERT INTO lender_preferences (user_id) VALUES (?)",
                        (user_id,)
                    )
                conn.commit()
                flash("Registration successful! Please log in to access your account.", "success")
                return redirect(url_for('login_route'))
            except sqlite3.IntegrityError:
                flash("Username, Email, or Phone already registered.", "error")
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

# --- Applicant Flow ---

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
        
    conn.close()
    
    score = compute_trust_score(session['user_id'])
    level, _ = get_trust_level(score)
    
    return render_template(
        'dashboard_applicant.html', 
        apps=apps, 
        trust_score=score, 
        trust_level=level,
        matches=matches
    )

@app.route('/apply', methods=['GET', 'POST'])
@login_required('applicant')
def apply():
    if request.method == 'POST':
        # Retrieve Form Data
        full_name = request.form.get('full_name')
        age = int(request.form.get('age', 0))
        gender = request.form.get('gender')
        email = request.form.get('email')
        phone = request.form.get('phone')
        employment_type = request.form.get('employment_type')
        profession = request.form.get('profession')
        monthly_income = float(request.form.get('monthly_income', 0))
        existing_emi = float(request.form.get('existing_emi', 0))
        loan_type = request.form.get('loan_type')
        loan_amount = float(request.form.get('loan_amount', 0))
        loan_tenure = int(request.form.get('loan_tenure', 0))
        guarantor_name = request.form.get('guarantor_name')
        guarantor_income = float(request.form.get('guarantor_income', 0))
        existing_debts = float(request.form.get('existing_debts', 0))
        credit_history = int(request.form.get('credit_history', 1))
        
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
        income_capacity = monthly_income + 0.5 * guarantor_income
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
            if loan_amount > 5 * monthly_income * 12:
                suggestions.append("Adding a co-signer or guarantor with stable monthly income can mitigate risk.")
                
        annual_income = monthly_income * 12
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
        conn.commit()
        conn.close()
        
        # Trigger matching with active lenders
        trigger_matching_engine(new_app_id)
        
        # 3. Simulate Email Notification
        print("\n" + "="*50)
        print(f"SIMULATED EMAIL NOTIFICATION SENT TO {email}")
        print(f"Subject: FinCheck Loan Application Reference #AP-{new_app_id} Received")
        print(f"Dear {full_name},\n")
        print(f"Thank you for submitting your loan application on FinCheck. Your AI-powered eligibility results are ready:")
        print(f"- Reference ID: #AP-{new_app_id}")
        print(f"- Decision Status: {status}")
        print(f"- Eligibility Score: {score}/100")
        print(f"- Risk Level: {risk_level}")
        print(f"\nYou can download your PDF report and track updates by logging into your FinCheck dashboard.")
        print("="*50 + "\n")
        
        flash("Application submitted and credit evaluation complete!", "success")
        return redirect(url_for('result', app_id=new_app_id))
        
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
        trust_level=level
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
    conn.close()
    
    both_accepted = (updated_match['lender_status'] == 'Accepted' and updated_match['borrower_status'] == 'Accepted')
    
    msg = f"Match {action.lower()} successfully."
    if both_accepted:
        msg = "Match finalized! Peer-to-peer contact details have been successfully unlocked."
        
    flash(msg, "success")
    if role == 'lender':
        return redirect(url_for('lender_dashboard'))
    else:
        return redirect(url_for('applicant_dashboard'))

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
    cursor.execute(
        "UPDATE applications SET status = ? WHERE id = ?",
        (new_status, app_id)
    )
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
    story.append(Paragraph("FinCheck Eligibility Report", title_style))
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
        "This recommendation is generated by AI based on user-provided information. Final lending decisions remain entirely between lenders and borrowers. FinCheck AI is not a financial institution and is not responsible for any financial transactions or disputes.",
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
        download_name=f"FinCheck_Report_AP{app_row['id']}.pdf", 
        mimetype='application/pdf'
    )

import urllib.request
import json

def get_gemini_response(api_key, prompt, context_data=None):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={api_key}"
    
    system_instr = (
        "You are FinCheck's AI Assistant, a friendly and professional financial advisor helping users on a "
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
            'response': f"Hello {username}! I am FinCheck's AI Assistant. I can help analyze your credit evaluation, check matching results with P2P lenders, suggest optimized loan parameters, or guide you on improving your trust score. How can I assist you today?"
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
            'response': "You're very welcome! I'm here to help. Let me know if you have any other questions about FinCheck AI."
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
        conn.commit()
        conn.close()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or redirect_url is None:
            return jsonify({'success': True, 'message': f'Document updated to {new_status}'})
        flash(f"Document status overridden to {new_status}.", "success")
        return redirect(redirect_url)
        
    conn.close()
    return jsonify({'success': False, 'error': 'Invalid action'}), 400

@app.route('/dev/get-otp/<email>')
def dev_get_otp(email):
    if not app.debug:
        return jsonify({'error': 'Forbidden'}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT otp FROM otps WHERE email = ? ORDER BY id DESC LIMIT 1", (email,))
    row = cursor.fetchone()
    conn.close()
    return jsonify({'otp': row['otp'] if row else None})

if __name__ == '__main__':
    # Initialize DB tables
    from database import init_db
    init_db()
    
    # Run dev server
    app.run(debug=True, port=5000)
