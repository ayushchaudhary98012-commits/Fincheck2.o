import sqlite3
import os
import json
from werkzeug.security import generate_password_hash

DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'database.db')

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            role TEXT NOT NULL DEFAULT 'applicant',
            otp_code TEXT,
            otp_expiry TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Safe migrations for existing users tables
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN otp_code TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN otp_expiry TIMESTAMP")
    except sqlite3.OperationalError:
        pass
    
    # Create Applications table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            age INTEGER NOT NULL,
            gender TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT NOT NULL,
            employment_type TEXT NOT NULL,
            profession TEXT NOT NULL,
            monthly_income REAL NOT NULL,
            existing_emi REAL NOT NULL,
            loan_type TEXT NOT NULL,
            loan_amount REAL NOT NULL,
            loan_tenure INTEGER NOT NULL,
            guarantor_name TEXT NOT NULL,
            guarantor_income REAL NOT NULL,
            existing_debts REAL NOT NULL,
            credit_history INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            approval_probability REAL,
            eligibility_score INTEGER,
            risk_level TEXT,
            reasons TEXT, -- JSON string storing explanation list
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    # Create Vendor Documents table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vendor_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            document_name TEXT NOT NULL,
            document_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            verification_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    
    # Check if a seed admin user exists, if not create one
    cursor.execute("SELECT * FROM users WHERE role = 'admin'")
    if not cursor.fetchone():
        admin_pass = generate_password_hash('admin123')
        cursor.execute(
            "INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)",
            ('admin', admin_pass, 'admin@fincheck.com', 'admin')
        )
        # Also create a default applicant for easy testing
        applicant_pass = generate_password_hash('user123')
        cursor.execute(
            "INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)",
            ('user', applicant_pass, 'user@fincheck.com', 'applicant')
        )
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    print("Initializing database...")
    init_db()
    print("Database initialized successfully.")
