# 🏦 FinTrust - AI-Powered Loan Eligibility & Financial Health Analysis System

FinTrust is a modern, full-stack financial technology platform designed to help applicants check their loan eligibility, receive detailed financial health ratings, and obtain Explainable AI (XAI) justifications for approvals and rejections. It also features a comprehensive Lender/Admin Portal with interactive charts, status overrides, and PDF report downloads.

---

## 🚀 Key Features

* **🤖 AI Eligibility Scoring**: Utilizes a Scikit-Learn `RandomForestClassifier` to compute a loan approval probability and maps it to a clear eligibility score (0–100).
* **🔍 Explainable AI (XAI)**: Demystifies automated decisions by showing applicants the exact positive and negative factors (e.g., debt-to-income ratio, guarantor income, credit history) influencing their score.
* **🛡️ Dual-Step OTP Verification**: Simulated 2FA (One-Time Passcode) security dispatch printed directly to the console logs and displayed on-screen for validation.
* **📊 Lender / Admin Dashboard**:
  * Real-time metrics tracking approved, pending, and rejected credit requests.
  * Interactive visualizations powered by Chart.js (status breakdown, monthly application volumes, risk distributions).
  * Filterable queue supporting application search, status overrides, pagination, and deletion.
* **🧮 Live EMI Calculator**: Slider-controlled tool providing instant calculations of installment fees, total principal, interest, and payoff amounts.
* **📄 PDF Exports**: Generates professional, clean breakdown reports as downloadable PDFs using `reportlab`.
* **🌓 Theme Switching**: Premium Glassmorphism UI styling with seamless dark/light mode synchronization.

---

## 📂 Repository Structure

The project separates the logic layer (`backend`) from the presentation assets (`frontend`):

```text
FinTrust--main/
├── backend/
│   ├── app.py                  # Main Flask application and API routes
│   ├── database.py             # SQLite database configuration and seeding
│   ├── train_model.py          # Synthetic dataset generator & ML model trainer
│   ├── requirements.txt        # Python package dependencies
│   ├── model.joblib            # Trained Random Forest classifier
│   └── scaler.joblib           # Pre-fitted StandardScaler for ML inputs
└── frontend/
    ├── templates/              # Jinja2 HTML views (landing, dashboard, login, calculator, etc.)
    └── static/                 # Stylesheets, JS modules, charts, and uploaded attachments
```

---

## 🛠️ Installation & Getting Started

Follow these steps to run FinTrust locally:

### 1. Install Dependencies
Ensure you have Python 3.8+ installed, then run:
```powershell
pip install -r backend/requirements.txt
```

### 2. Initialize Database & Seed Users
Set up the SQLite database structure and pre-seed test credentials:
```powershell
python backend/database.py
```

### 3. Train the ML Model (Optional)
If you want to regenerate training data and rebuild the classification model:
```powershell
python backend/train_model.py
```

### 4. Run the Server
Launch the Flask development server:
```powershell
python backend/app.py
```
Open **`http://127.0.0.1:5000`** in your browser to view the application.

---

## 🔑 Demo Accounts

Use these credentials to log in and explore both perspectives of the application:

| Portal Role | Username | Password |
| :--- | :--- | :--- |
| **Lender / Admin** | `admin` | `admin123` |
| **Applicant / Customer** | `user` | `user123` |

*(Note: During OTP verification, the 6-digit passcode will be flashed directly on-screen or output to your terminal/console logs.)*
