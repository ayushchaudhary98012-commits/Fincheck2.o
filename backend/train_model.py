import os
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, roc_auc_score
import joblib

# Set random seed for reproducibility
np.random.seed(42)

def calculate_emi(amount, rate_annual, tenure_months):
    r = rate_annual / 12.0
    if r == 0:
        return amount / tenure_months
    return (amount * r * (1 + r)**tenure_months) / ((1 + r)**tenure_months - 1)

def generate_synthetic_data(num_samples=1000):
    # Features
    monthly_income = np.random.uniform(2000, 18000, num_samples)
    
    # Existing EMI: average 15% of income, max 40%
    existing_emi = monthly_income * np.random.beta(a=2, b=8, size=num_samples)
    
    # Employment Type: 0 = Self-Employed, 1 = Salaried
    employment_type = np.random.choice([0, 1], size=num_samples, p=[0.3, 0.7])
    
    # Loan Amount: generally 2x to 8x of annual income (with variance)
    annual_income = monthly_income * 12
    loan_amount = annual_income * np.random.uniform(1.5, 6.0, num_samples)
    loan_amount = np.round(loan_amount, -2) # round to nearest hundred
    
    # Loan Tenure: months (12 to 360)
    loan_tenure = np.random.choice([12, 24, 36, 48, 60, 120, 180, 240, 360], size=num_samples)
    
    # Credit History: 0 = Bad, 1 = Good (80% good credit)
    credit_history = np.random.choice([0, 1], size=num_samples, p=[0.2, 0.8])
    
    # Guarantor Income: 60% have 0, 40% have some income (relative to applicant)
    has_guarantor = np.random.choice([0, 1], size=num_samples, p=[0.6, 0.4])
    guarantor_income = has_guarantor * (monthly_income * np.random.uniform(0.3, 1.2, num_samples))
    
    # Existing debts (other than EMIs, e.g. credit card debt, other balances)
    existing_debts = loan_amount * np.random.beta(a=1, b=5, size=num_samples)
    existing_debts = np.round(existing_debts, -2)
    
    # Calculate New EMI (9% interest rate)
    new_emis = np.array([calculate_emi(la, 0.09, lt) for la, lt in zip(loan_amount, loan_tenure)])
    
    # Targets based on financial heuristics
    y = []
    probabilities = []
    
    for i in range(num_samples):
        # DTI: Total debt service / (applicant income + 50% guarantor income)
        dti = (existing_emi[i] + new_emis[i]) / (monthly_income[i] + 0.5 * guarantor_income[i])
        
        # Credit history is the strongest factor
        if credit_history[i] == 1:
            base_p = 0.85
            # Reduce probability for high DTI
            if dti > 0.45:
                base_p -= 0.30
            if dti > 0.60:
                base_p -= 0.40
            # Reduce for low monthly income
            if monthly_income[i] < 3500:
                base_p -= 0.15
            # Increase slightly for salaried
            if employment_type[i] == 1:
                base_p += 0.05
        else: # Credit history is bad
            base_p = 0.10
            # High income and low DTI can slightly rescue bad credit
            if dti < 0.30 and monthly_income[i] > 8000:
                base_p += 0.20
            # Strong guarantor backing helps
            if guarantor_income[i] > 0.8 * monthly_income[i]:
                base_p += 0.25
        
        # Add random noise
        noise = np.random.normal(0, 0.05)
        prob = np.clip(base_p + noise, 0.01, 0.99)
        probabilities.append(prob)
        y.append(1 if prob >= 0.5 else 0)
        
    # Create DataFrame
    df = pd.DataFrame({
        'monthly_income': monthly_income,
        'existing_emi': existing_emi,
        'employment_type': employment_type,
        'loan_amount': loan_amount,
        'loan_tenure': loan_tenure,
        'credit_history': credit_history,
        'guarantor_income': guarantor_income,
        'existing_debts': existing_debts,
        'approved': y
    })
    
    return df

def train_and_save():
    print("Generating synthetic financial data...")
    df = generate_synthetic_data(1000)
    
    # Save CSV
    os.makedirs(os.path.join(os.path.dirname(__file__), 'data'), exist_ok=True)
    csv_path = os.path.join(os.path.dirname(__file__), 'data', 'sample_loans.csv')
    df.to_csv(csv_path, index=False)
    print(f"Dataset saved to {csv_path}")
    
    # Features & target
    feature_cols = [
        'monthly_income', 
        'existing_emi', 
        'employment_type', 
        'loan_amount', 
        'loan_tenure', 
        'credit_history', 
        'guarantor_income'
    ]
    X = df[feature_cols]
    y = df['approved']
    
    # Split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    # Fit scaler
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Train Random Forest Classifier
    print("Training Random Forest Classifier...")
    model = RandomForestClassifier(n_estimators=100, max_depth=8, random_state=42)
    model.fit(X_train_scaled, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test_scaled)
    y_prob = model.predict_proba(X_test_scaled)[:, 1]
    
    print("\nModel Evaluation Report:")
    print(classification_report(y_test, y_pred))
    print(f"ROC AUC Score: {roc_auc_score(y_test, y_prob):.4f}")
    
    # Feature Importances
    importances = model.feature_importances_
    print("\nFeature Importances:")
    for col, imp in zip(feature_cols, importances):
        print(f"  {col}: {imp:.4f}")
        
    # Save model and scaler
    model_path = os.path.join(os.path.dirname(__file__), 'model.joblib')
    scaler_path = os.path.join(os.path.dirname(__file__), 'scaler.joblib')
    
    joblib.dump(model, model_path)
    joblib.dump(scaler, scaler_path)
    print(f"\nModel and Scaler successfully saved to {os.path.dirname(__file__)}")

if __name__ == '__main__':
    train_and_save()
