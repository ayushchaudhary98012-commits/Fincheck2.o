# 🚀 FinTrust - Comprehensive Deployment Guide

This guide provides step-by-step instructions for deploying **FinTrust** with a **decoupled architecture**:
1. **Backend REST API** hosted on **Render** (or Railway / Docker / AWS).
2. **Frontend Client Application** hosted on **Vercel** (or Netlify / Cloudflare Pages).

---

## 🏗️ Architecture Overview

```text
  ┌────────────────────────┐                   ┌────────────────────────┐
  │   Frontend Web App     │   HTTPS / REST    │   Backend REST API     │
  │   (Vercel / Netlify)   │ ────────────────► │  (Render / Railway)    │
  │   Static HTML/CSS/JS   │   JSON Payloads   │  Flask + ML + SQLite   │
  └────────────────────────┘                   └────────────────────────┘
```

---

## 1. ⚙️ Deploying the Backend API (Render)

### Option A: Standard Render Web Service Deployment

1. **Push your code to GitHub / GitLab**.
2. Log into [Render Dashboard](https://dashboard.render.com/) and click **New +** ➔ **Web Service**.
3. Connect your repository.
4. Select the `backend` directory as the root folder or select **Blueprint** to use `backend/render.yaml`.
5. Configure the build parameters:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Root Directory**: `backend`
6. Click **Create Web Service**. Render will deploy your Flask REST API and provide a live HTTPS URL (e.g. `https://fintrust-backend-api.onrender.com`).

### Option B: Docker Container Deployment

If you prefer deploying via Docker on Render, Railway, or AWS:
```bash
cd backend
docker build -t fintrust-backend .
docker run -p 5000:5000 fintrust-backend
```

---

## 2. 🌐 Deploying the Standalone Frontend (Vercel)

1. Log into [Vercel Dashboard](https://vercel.com/) and click **Add New Project**.
2. Import your Git repository containing the `frontend` folder.
3. Set the **Framework Preset** to **Other / Static Store**.
4. Set the **Root Directory** to `frontend`.
5. Update `frontend/static/js/config.js` or configure Environment Variable `API_BASE_URL`:
   ```javascript
   const API_BASE_URL = 'https://fintrust-backend-api.onrender.com';
   ```
6. Click **Deploy**. Vercel will build and deploy your frontend to a global edge CDN with a free HTTPS URL (e.g., `https://fintrust.vercel.app`).

---

## 3. 🧪 Testing & Verification

Once both services are deployed:
1. Open your live Frontend URL (e.g., `https://fintrust.vercel.app`).
2. Test user login with test accounts (`admin` / `admin123` or `user` / `user123`).
3. Verify cross-origin API calls for:
   - Loan Eligibility Predictions (Scikit-Learn ML)
   - Live EMI Calculations
   - OTP Passcode Dispatch
   - Agreement Creation & PDF Download
   - Lender Matchmaking & Admin Override
