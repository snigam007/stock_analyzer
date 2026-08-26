# 🚀 1-Click Streamlit Community Cloud Deployment Guide

This guide enables you to deploy the **Autonomous Quantitative Trading & Analytics Platform** to **Streamlit Community Cloud** (100% Free) so you can access all 12 pages seamlessly on your **mobile phone, tablet, and laptop simultaneously** from anywhere in the world.

---

## 📱 Architecture & Execution Model
- **Where does it execute?**: On high-speed cloud container infrastructure managed by Streamlit (AWS/GCP edge servers).
- **Can you check on mobile and laptop?**: **YES!** You receive a persistent public/private web URL (e.g. `https://your-quant-platform.streamlit.app`) that renders in real-time with responsive touch-friendly mobile layouts.
- **Can you still run locally?**: **YES!** Your local environment (`http://localhost:8501`) remains completely independent and fully synchronized via Git.

---

## 🛠️ Step-by-Step Deployment Protocol

### Step 1: Push Codebase to GitHub
1. Create a repository on GitHub (e.g., `indian-stock-quant-platform`).
2. Link your local directory and push:
   ```bash
   git remote add origin https://github.com/<your-github-username>/indian-stock-quant-platform.git
   git branch -M main
   git push -u origin main
   ```

---

### Step 2: Deploy on Streamlit Community Cloud
1. Go to **[share.streamlit.io](https://share.streamlit.io/)** and sign in with your GitHub account.
2. Click **"New app"**.
3. Select your repository: `<your-github-username>/indian-stock-quant-platform`.
4. Set **Main file path**: `app/1_Dashboard.py` (or `1_Dashboard.py`).
5. Click **"Deploy!"**.

---

### Step 3: Mobile PWA Shortcut (Instant Access)
- **On iPhone (iOS / Safari)**: Open your Streamlit URL $\rightarrow$ Tap the **Share** button $\rightarrow$ Tap **"Add to Home Screen"**.
- **On Android (Chrome)**: Open your Streamlit URL $\rightarrow$ Tap the **3 dots** $\rightarrow$ Tap **"Install App"** / **"Add to Home screen"**.

🎉 You now have a high-speed Bloomberg-level quantitative powerhouse running right on your smartphone!