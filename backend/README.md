# FinCheck - AI-Powered Loan Eligibility & Financial Health Analysis System

FinCheck is a modern, full-stack fintech platform designed to help applicants check their loan eligibility, receive detailed financial health ratings, and obtain Explainable AI (XAI) justifications for approval and rejection. It also provides a lender portal with dashboard analytics, searches/filters, status overriding capabilities, and PDF generation.

---

## Key Features

1. **AI Eligibility Scoring**: Utilizes a Scikit-Learn `RandomForestClassifier` to output approval probability and an eligibility score (0–100).
2. **Explainable AI (XAI)**: Identifies exactly which features (like high debt service, poor credit history, or guarantor backing) influenced the model's decision, providing positive and negative factor lists.
3. **Lender/Admin Dashboard**:
   - Aggregate counts (Total, Approved, Rejected, Pending).
   - Dynamic charts powered by Chart.js (Pie chart of statuses, bar chart of monthly counts, doughnut chart of risk distributions).
   - Queue tables supporting search, status overrides, pagination, and deletion.
4. **Interactive EMI Calculator**: Live sliding controls for amount, interest rate, and tenure, providing immediate calculations of installment fees, total principal, interest, and payoff totals.
5. **PDF Report Exports**: Generates and downloads a clean, professional financial breakdown report as a PDF using `reportlab`.
6. **Dark / Light Mode**: Seamless UI transition matching premium modern banking portals.
7. **Simulated Email Notifications**: Prints detailed transactional logs directly to the server terminal.

---

## Directory Structure

```
fincheck/
├── app.py                      # Flask application and REST routing
├── database.py                 # SQLite database schema definition and helpers
├── train_model.py              # ML model dataset generator and trainer
├── requirements.txt            # Python package dependencies
├── README.md                   # Setup documentation (this file)
├── static/                     # Assets served directly by Flask
│   ├── css/
│   │   └── styles.css          # Main styling sheets (Glassmorphic dark/light variables)
│   └── js/
│       ├── main.js             # General actions (theme switches, forms validations)
│       ├── charts.js           # Chart.js visualization loaders
│       └── calculator.js       # Live EMI calculator engine
└── templates/                  # Jinja2 HTML pages
    ├── base.html               # Main base layout wrapper
    ├── landing.html            # Landing / Hero section
    ├── login.html              # Login & registration toggles
    ├── apply.html              # Multi-step credit check application
    ├── result.html             # Analysis results, gauge, risk, XAI lists
    ├── dashboard_applicant.html# Applicant history tables
    ├── dashboard_admin.html    # Lender admin controls & analytics charts
    └── calculator.html         # Standalone calculator widget page
```

---

## Installation & Setup

1. **Navigate to the Project Folder**:
   ```powershell
   cd fincheck
   ```

2. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

3. **Train the ML Model**:
   Run the model script to generate the training dataset (1,000 profiles) and train the classifier:
   ```powershell
   python train_model.py
   ```
   This will output model accuracy/AUC reports and save the serialized model as `model.joblib` and `scaler.joblib`.

4. **Initialize the Database**:
   Initialize tables and seed initial users in SQLite:
   ```powershell
   python database.py
   ```

5. **Start the Application**:
   Launch the Flask server:
   ```powershell
   python app.py
   ```
   The application will run locally at **`http://127.0.0.1:5000`**.

---

## Accounts for Testing

The database comes pre-seeded with two testing accounts:

* **Lender / Admin User**:
  - **Username**: `admin`
  - **Password**: `admin123`
* **Applicant / Customer User**:
  - **Username**: `user`
  - **Password**: `user123`

*(You can also use the registration tab on the login page to create a new admin or applicant account dynamically.)*
