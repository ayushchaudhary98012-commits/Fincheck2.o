import unittest
import json
import os
import sqlite3
from werkzeug.security import generate_password_hash
from app import app, get_db_connection
from database import init_db

class FinTrustTestCase(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        
        # Initialize and clear DB
        init_db()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM applications")
        cursor.execute("DELETE FROM users")
        conn.commit()
        
        # Re-seed test users
        admin_pass = generate_password_hash('admin123')
        cursor.execute(
            "INSERT INTO users (username, password_hash, email, phone, role) VALUES (?, ?, ?, ?, ?)",
            ('admin', admin_pass, 'admin@fintrust.com', '+1111111111', 'admin')
        )
        applicant_pass = generate_password_hash('user123')
        cursor.execute(
            "INSERT INTO users (username, password_hash, email, phone, role) VALUES (?, ?, ?, ?, ?)",
            ('user', applicant_pass, 'user@fintrust.com', '+2222222222', 'applicant')
        )
        conn.commit()
        conn.close()
        
    def register_and_login(self, username, password, email, phone, role='applicant'):
        # 1. Register (which triggers pending registration and OTP generation)
        self.client.post('/login', data={
            'action': 'register',
            'username': username,
            'email': email,
            'phone': phone,
            'role': role,
            'password': password,
            'confirm_password': password
        }, follow_redirects=True)
        
        # 2. Retrieve the generated OTP from SQLite database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT otp FROM otps WHERE email = ?", (email,))
        otp_row = cursor.fetchone()
        conn.close()
        
        if not otp_row:
            raise ValueError(f"No OTP generated for registration of {username} (email: {email})")
        otp = otp_row['otp']
        
        # 3. Submit OTP code to verify and finalize registration/login
        return self.client.post('/api/auth/verify-otp', data={
            'email': email,
            'otp': otp
        }, follow_redirects=True)

    def login_existing_user(self, username, password):
        # Direct login with username/password
        return self.client.post('/login', data={
            'action': 'login',
            'username': username,
            'password': password
        }, follow_redirects=True)
        
    def tearDown(self):
        pass

    def test_landing_and_calculator(self):
        # Test Landing Page loads
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Trust Scoring', res.data)
        self.assertIn(b'P2P Matching', res.data)
        
        # Test Calculator Page loads
        res = self.client.get('/calculator')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Interactive EMI Calculator', res.data)

    def test_authentication(self):
        # Test GET login page
        res = self.client.get('/login')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Login', res.data)
        
        # Test dynamic registration (requires OTP verification)
        res = self.register_and_login('test_applicant', 'testpassword', 'applicant@test.com', '+2222222222')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Borrower Dashboard', res.data) # should land on applicant dashboard
        
        # Test logout
        res = self.client.get('/logout', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Successfully logged out.', res.data)
        
        # Test login with seed admin credentials
        res = self.login_existing_user('admin', 'admin123')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Lender Administration Portal', res.data)

    def test_loan_application_and_prediction(self):
        # 1. Register and login applicant
        self.register_and_login('john_doe', 'password123', 'john.doe@test.com', '1234567890')
        
        # 2. Submit Loan Application Form
        res = self.client.post('/apply', data={
            'full_name': 'John Doe',
            'age': '35',
            'gender': 'Male',
            'email': 'john.doe@test.com',
            'phone': '1234567890',
            'employment_type': 'Salaried',
            'profession': 'Developer',
            'monthly_income': '8500',
            'existing_emi': '400',
            'loan_type': 'Home',
            'loan_amount': '150000',
            'loan_tenure': '120',
            'guarantor_name': 'Jane Doe',
            'guarantor_income': '3000',
            'existing_debts': '1500',
            'credit_history': '1'
        }, follow_redirects=True)
        
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'John Doe', res.data)
        self.assertIn(b'Eligibility Score', res.data)
        self.assertIn(b'Download PDF Report', res.data)
        
        # 3. Verify database insertion
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM applications WHERE full_name = 'John Doe'")
        app_record = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(app_record)
        self.assertIn(app_record['status'], ['Approved', 'Moderate'])
        self.assertGreaterEqual(app_record['eligibility_score'], 40)
        self.assertIn(app_record['risk_level'], ['Low', 'Medium'])
        
        # 4. Verify PDF report endpoint
        pdf_res = self.client.get(f"/api/applications/{app_record['id']}/pdf")
        self.assertEqual(pdf_res.status_code, 200)
        self.assertEqual(pdf_res.mimetype, 'application/pdf')
        
    def test_admin_endpoints(self):
        # Login as Admin
        self.login_existing_user('admin', 'admin123')
        
        # Submit an application first so stats are populated
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = 'admin'")
        admin_id = cursor.fetchone()[0]
        cursor.execute('''
            INSERT INTO applications (
                user_id, full_name, age, gender, email, phone, employment_type, profession,
                monthly_income, existing_emi, loan_type, loan_amount, loan_tenure,
                guarantor_name, guarantor_income, existing_debts, credit_history,
                status, approval_probability, eligibility_score, risk_level, reasons
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            admin_id, 'Admin Test Applicant', 40, 'Female', 'test@test.com', '12345', 'Salaried', 'Director',
            10000.0, 500.0, 'Business', 200000.0, 60, 'Sponsor', 5000.0, 0.0, 1,
            'Approved', 0.95, 95, 'Low', '[]'
        ))
        app_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # Test Stats REST API
        res = self.client.get('/api/admin/stats')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertIn('stats', data)
        self.assertEqual(data['stats']['status_counts']['Approved'], 1)
        
        # Test status override
        override_res = self.client.post(f"/admin/applications/{app_id}/status", data={
            'status': 'Rejected'
        }, follow_redirects=True)
        self.assertEqual(override_res.status_code, 200)
        self.assertIn(b'Rejected', override_res.data)
        
        # Check DB to verify status is changed
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM applications WHERE id = ?", (app_id,))
        app_status = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(app_status, 'Rejected')
        
        # Test application deletion
        delete_res = self.client.post(f"/admin/applications/{app_id}/delete", follow_redirects=True)
        self.assertEqual(delete_res.status_code, 200)
        self.assertIn(b'has been deleted.', delete_res.data)
        
        # Verify it's gone from database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
        deleted_record = cursor.fetchone()
        conn.close()
        self.assertIsNone(deleted_record)

    def test_vendor_document_verification(self):
        # 1. Register and login applicant
        self.register_and_login('vendor_test', 'password123', 'vendor@test.com', '1234567890')
        
        # 2. Check initial trust details
        res = self.client.get('/api/vendor/trust-score')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['score'], 30) # base score
        self.assertEqual(data['level'], 'Bronze')
        
        # 3. Simulate file upload (valid mock file)
        import io
        file_data = (io.BytesIO(b"dummy business license content"), 'license.pdf')
        res = self.client.post('/api/vendor/upload', data={
            'file': file_data,
            'document_type': 'pan_verification'
        })
        self.assertEqual(res.status_code, 200)
        upload_data = json.loads(res.data)
        self.assertTrue(upload_data['success'])
        self.assertEqual(upload_data['status'], 'Verified') # auto-verified
        
        # 4. Check trust details again (should increase score by 15 points -> 45 points -> Bronze level)
        res = self.client.get('/api/vendor/trust-score')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['score'], 45)
        self.assertEqual(data['level'], 'Bronze')
        
        # Upload another document: Aadhaar Card (+15 points)
        file_data2 = (io.BytesIO(b"dummy aadhaar details"), 'aadhaar.pdf')
        res = self.client.post('/api/vendor/upload', data={
            'file': file_data2,
            'document_type': 'aadhaar_verification'
        })
        self.assertEqual(res.status_code, 200)
        
        # Upload another document: Bank Statement (+15 points)
        file_data3 = (io.BytesIO(b"dummy bank details"), 'bank.pdf')
        res = self.client.post('/api/vendor/upload', data={
            'file': file_data3,
            'document_type': 'bank_statement'
        })
        self.assertEqual(res.status_code, 200)
        
        # Now score is 30 + 15 + 15 + 15 = 75 points -> Gold level!
        res = self.client.get('/api/vendor/trust-score')
        data = json.loads(res.data)
        self.assertEqual(data['score'], 75)
        self.assertEqual(data['level'], 'Gold')
        
        # 5. Login as Admin to reject the last document
        self.client.get('/logout')
        self.login_existing_user('admin', 'admin123')
        
        # Find document id for bank_statement
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM vendor_documents WHERE document_type = 'bank_statement' ORDER BY id DESC LIMIT 1")
        doc_row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(doc_row)
        doc_id = doc_row['id']
        
        # Reject document
        res = self.client.post(f"/admin/documents/{doc_id}/status", data={
            'status': 'Rejected'
        })
        self.assertEqual(res.status_code, 200)
        
        # 6. Check trust details again for user (should be 30 + 15 + 15 = 60 points -> Silver level)
        self.client.get('/logout')
        self.login_existing_user('vendor_test', 'password123')
        
        res = self.client.get('/api/vendor/trust-score')
        data = json.loads(res.data)
        self.assertEqual(data['score'], 60)
        self.assertEqual(data['level'], 'Silver')

    def test_vendor_document_verification_with_fake_content(self):
        # 1. Register and login applicant
        self.register_and_login('vendor_test_fake', 'password123', 'vendor_fake@test.com', '1234567890')
        
        # 2. Simulate file upload with 'fake' in file contents but valid filename
        import io
        file_data = (io.BytesIO(b"this is a fake document content"), 'valid_license_name.pdf')
        res = self.client.post('/api/vendor/upload', data={
            'file': file_data,
            'document_type': 'pan_verification'
        })
        self.assertEqual(res.status_code, 200)
        upload_data = json.loads(res.data)
        self.assertEqual(upload_data['status'], 'Rejected') # should be rejected due to content

    def test_lender_document_verification(self):
        # 1. Register and login lender
        self.register_and_login('lender_test_verif', 'password123', 'lender_verif@test.com', '0987654321', role='lender')
        
        # Access lender dashboard (should render fine)
        res = self.client.get('/lender/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Lender Trust Profile Verification', res.data)
        
        # 2. Check initial trust details (should start at 30, level Bronze)
        res = self.client.get('/api/vendor/trust-score')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['score'], 30)
        
        # 3. Simulate file upload (valid mock PAN card file -> +15 points)
        import io
        file_data = (io.BytesIO(b"dummy pan card image data"), 'pan.png')
        res = self.client.post('/api/vendor/upload', data={
            'file': file_data,
            'document_type': 'pan_verification'
        })
        self.assertEqual(res.status_code, 200)
        upload_data = json.loads(res.data)
        self.assertTrue(upload_data['success'])
        self.assertEqual(upload_data['status'], 'Verified')
        
        # Check trust details again (should be 45)
        res = self.client.get('/api/vendor/trust-score')
        data = json.loads(res.data)
        self.assertEqual(data['score'], 45)

    def test_otp_verification_flow(self):
        # 1. Trigger registration to generate OTP
        self.client.post('/login', data={
            'action': 'register',
            'username': 'test_registration_flow',
            'email': 'reg_flow@test.com',
            'phone': '1234567890',
            'role': 'applicant',
            'password': 'password123',
            'confirm_password': 'password123'
        })
        
        # 2. Verify invalid OTP returns error
        res = self.client.post('/api/auth/verify-otp', data={
            'email': 'reg_flow@test.com',
            'otp': '999999'
        }, follow_redirects=True)
        self.assertIn(b'Invalid OTP', res.data)
        
        # 3. Retrieve the generated OTP from DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT otp FROM otps WHERE email = 'reg_flow@test.com'")
        otp_row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(otp_row)
        otp = otp_row['otp']
        
        # 4. Verify correct OTP works, creating the user and logging in
        res = self.client.post('/api/auth/verify-otp', data={
            'email': 'reg_flow@test.com',
            'otp': otp
        }, follow_redirects=True)
        self.assertIn(b'Logged in successfully', res.data)

    def test_notifications_flow(self):
        # 1. Register and login a user
        self.client.post('/login', data={
            'action': 'register',
            'username': 'notif_user',
            'email': 'notif_user@test.com',
            'phone': '1234567890',
            'role': 'applicant',
            'password': 'password123',
            'confirm_password': 'password123'
        })
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT otp FROM otps WHERE email = 'notif_user@test.com'")
        otp = cursor.fetchone()['otp']
        conn.close()
        
        self.client.post('/api/auth/verify-otp', data={
            'email': 'notif_user@test.com',
            'otp': otp
        }, follow_redirects=True)
        
        # 2. Submit a loan application
        self.client.post('/apply', data={
            'full_name': 'Notif User',
            'age': '30',
            'gender': 'Male',
            'email': 'notif_user@test.com',
            'phone': '1234567890',
            'employment_type': 'Salaried',
            'profession': 'Developer',
            'monthly_income': '15000',
            'existing_emi': '1000',
            'loan_type': 'Personal',
            'loan_amount': '500000',
            'loan_tenure': '24',
            'guarantor_name': 'None',
            'guarantor_income': '0',
            'existing_debts': '0',
            'credit_history': '1'
        })
        
        # 3. Retrieve notifications and verify submission notification
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM notifications")
        notifs = cursor.fetchall()
        conn.close()
        
        self.assertGreater(len(notifs), 0)
        self.assertEqual(notifs[0]['title'], "Loan Application Submitted")
        self.assertEqual(notifs[0]['type'], "info")
        
        # Get application ID
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM applications WHERE email = 'notif_user@test.com'")
        app_id = cursor.fetchone()['id']
        conn.close()
        
        # 4. Update status as admin and verify notification
        # Login as admin
        self.client.get('/logout', follow_redirects=True)
        self.client.post('/login', data={
            'action': 'login',
            'username': 'admin@fintrust.com',
            'password': 'admin123'
        }, follow_redirects=True)
        
        self.client.post(f'/admin/applications/{app_id}/status', data={
            'status': 'Approved'
        }, follow_redirects=True)
        
        # Check database for approval notification
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM notifications WHERE type = 'success'")
        admin_notifs = cursor.fetchall()
        conn.close()
        self.assertEqual(len(admin_notifs), 1)
        self.assertIn("Approved", admin_notifs[0]['title'])
        
        # 5. Clear notifications and verify is_read
        # Logout admin and login user
        self.client.get('/logout', follow_redirects=True)
        self.client.post('/login', data={
            'action': 'login',
            'username': 'notif_user@test.com',
            'password': 'password123'
        }, follow_redirects=True)
        
        res = self.client.post('/api/notifications/clear', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        
        # Verify in database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM notifications WHERE is_read = 0")
        unread_count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(unread_count, 0)

if __name__ == '__main__':
    unittest.main()
