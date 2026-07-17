import os
import io
import json
import sqlite3
from functools import wraps
from datetime import datetime, timedelta
import random
import pandas as pd
import numpy as np
import joblib

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash

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

# Trust Score Rating System Helpers
def compute_trust_score(user_id):
    score = 30
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check verified documents
    cursor.execute("SELECT document_type FROM vendor_documents WHERE user_id = ? AND status = 'Verified'", (user_id,))
    verified_types = [row['document_type'] for row in cursor.fetchall()]
    
    if 'pan_verification' in verified_types:
        score += 30
    if 'bank_statement' in verified_types:
        score += 20
    if 'identity_proof' in verified_types:
        score += 20
        
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
            conn.close()
            
            if user and check_password_hash(user['password_hash'], password):
                # Generate 6-digit OTP code
                otp = f"{random.randint(100000, 999999)}"
                expiry = (datetime.now() + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
                
                # Save OTP to database
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET otp_code = ?, otp_expiry = ? WHERE id = ?",
                    (otp, expiry, user['id'])
                )
                conn.commit()
                conn.close()
                
                # Staged user session identifier
                session['pre_auth_user_id'] = user['id']
                
                # Print simulated OTP to console log
                print("\n" + "="*50)
                print(f"SIMULATED OTP DISPATCH")
                print(f"To Username: {user['username']}")
                print(f"Masked Email: {user['email']}")
                print(f"Masked Phone: {user['phone']}")
                print(f"ONE-TIME PASSCODE: {otp}")
                print("="*50 + "\n")
                
                # Flash OTP code for demonstration convenience
                flash(f"[DEMO ONLY] OTP code sent: {otp}", "info")
                
                return redirect(url_for('otp_verification_route'))
            else:
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
                conn.commit()
                flash("Registration successful! Please log in to verify your account using OTP.", "success")
                return redirect(url_for('login_route'))
            except sqlite3.IntegrityError:
                flash("Username, Email, or Phone already registered.", "error")
            finally:
                conn.close()
                
    return render_template('login.html')

@app.route('/logout')
def logout_route():
    session.clear()
    flash("Successfully logged out.", "success")
    return redirect(url_for('landing'))

# --- Two-Step OTP Verification Helpers & Routes ---

def mask_email(email):
    if not email or '@' not in email:
        return email
    parts = email.split('@')
    name = parts[0]
    domain = parts[1]
    if len(name) <= 2:
        masked_name = name[0] + '*'
    else:
        masked_name = name[0] + '*' * (len(name) - 2) + name[-1]
    return f"{masked_name}@{domain}"

def mask_phone(phone):
    if not phone:
        return "Not Provided"
    if len(phone) <= 4:
        return "****"
    return "*" * (len(phone) - 4) + phone[-4:]

@app.route('/login/otp', methods=['GET', 'POST'])
def otp_verification_route():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('applicant_dashboard'))
        
    pre_auth_id = session.get('pre_auth_user_id')
    if not pre_auth_id:
        flash("Please log in first.", "error")
        return redirect(url_for('login_route'))
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (pre_auth_id,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        flash("User record not found.", "error")
        return redirect(url_for('login_route'))
        
    if request.method == 'POST':
        entered_otp = request.form.get('otp', '').strip()
        
        # Check expiry
        now = datetime.now()
        expiry_dt = None
        if user['otp_expiry']:
            try:
                expiry_dt = datetime.strptime(user['otp_expiry'], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                pass
                
        if not expiry_dt or now > expiry_dt:
            flash("Verification code has expired. Please request a new one.", "error")
            return render_template('otp.html', email_masked=mask_email(user['email']), phone_masked=mask_phone(user['phone']))
            
        if entered_otp == user['otp_code']:
            # Clear OTP in database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET otp_code = NULL, otp_expiry = NULL WHERE id = ?", (user['id'],))
            conn.commit()
            conn.close()
            
            # Elevate to active session
            session.pop('pre_auth_user_id', None)
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            
            flash(f"Welcome, {user['username']}! Verification successful.", "success")
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('applicant_dashboard'))
        else:
            flash("Incorrect verification code.", "error")
            
    # Mask details for display
    email_masked = mask_email(user['email'])
    phone_masked = mask_phone(user['phone'])
    
    return render_template('otp.html', email_masked=email_masked, phone_masked=phone_masked)

@app.route('/login/otp/resend', methods=['POST'])
def otp_resend_route():
    pre_auth_id = session.get('pre_auth_user_id')
    if not pre_auth_id:
        flash("Please log in first.", "error")
        return redirect(url_for('login_route'))
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (pre_auth_id,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        flash("User record not found.", "error")
        return redirect(url_for('login_route'))
        
    # Generate a new 6-digit OTP code
    otp = f"{random.randint(100000, 999999)}"
    expiry = (datetime.now() + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute(
        "UPDATE users SET otp_code = ?, otp_expiry = ? WHERE id = ?",
        (otp, expiry, user['id'])
    )
    conn.commit()
    conn.close()
    
    # Print simulated OTP to console log
    print("\n" + "="*50)
    print(f"RESENT SIMULATED OTP DISPATCH")
    print(f"To Username: {user['username']}")
    print(f"Masked Email: {user['email']}")
    print(f"Masked Phone: {user['phone']}")
    print(f"ONE-TIME PASSCODE: {otp}")
    print("="*50 + "\n")
    
    flash(f"[DEMO ONLY] New OTP code sent: {otp}", "info")
    return redirect(url_for('otp_verification_route'))

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
    conn.close()
    
    score = compute_trust_score(session['user_id'])
    level, _ = get_trust_level(score)
    
    return render_template(
        'dashboard_applicant.html', 
        apps=apps, 
        trust_score=score, 
        trust_level=level
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
        trust_color=trust_color
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
        
    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#E2E8F0'), spaceAfter=15))
    story.append(Paragraph("<i>Disclaimer: This report represents automated AI underwriting prediction and does not constitute a binding legal credit agreement.</i>", ParagraphStyle('Discl', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#94A3B8'))))
    
    # Build Document
    doc.build(story)
    buffer.seek(0)
    
    return send_file(
        buffer, 
        as_attachment=True, 
        download_name=f"FinCheck_Report_AP{app_row['id']}.pdf", 
        mimetype='application/pdf'
    )

# --- Vendor Document Verification Routes ---

@app.route('/applicant/verification')
@login_required('applicant')
def vendor_verification_ui():
    return render_template('verification.html')

@app.route('/api/vendor/upload', methods=['POST'])
@login_required('applicant')
def vendor_upload_document():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file segment in request'}), 400
    file = request.files['file']
    doc_type = request.form.get('document_type')
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
        
    if not doc_type or doc_type not in ['pan_verification', 'bank_statement', 'identity_proof']:
        return jsonify({'success': False, 'error': 'Invalid document category'}), 400
        
    if file and allowed_file(file.filename):
        filename = f"user_{session['user_id']}_{doc_type}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Simulated AI Document Verification check (OCR & Registry lookup mock)
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

if __name__ == '__main__':
    # Initialize DB tables
    from database import init_db
    init_db()
    
    # Run dev server
    app.run(debug=True, port=5000)
