# SmartCivic — Credentials & Quickstart Run Guide

This document contains all login credentials, account roles, environment setup instructions, and terminal commands to run and test SmartCivic from start to finish.

---

## 1. Login Credentials & Accounts

All pre-seeded default accounts share the master seed password:
> **Default Password:** `smartcivic123`

### Account Directory

| Role | Name / Title | Email Address | Password | Ward / Scope | Portal URL |
|:---|:---|:---|:---|:---|:---|
| **Resident (Citizen)** | Resident Citizen | `citizen@smartcivic.com` | `smartcivic123` | Ward 1 (Verified) | `http://localhost:5000/citizen/dashboard` |
| **Ward Officer** | Ward Officer 1 | `officer@smartcivic.com` | `smartcivic123` | Ward 1 | `http://localhost:5000/officer/dashboard` |
| **Central Authority** | Central Authority | `authority@smartcivic.com` | `smartcivic123` | All Wards (`all`) | `http://localhost:5000/officer/dashboard` |
| **System Admin** | System Administrator | `admin@smartcivic.com` | `smartcivic123` | All Wards (`all`) | `http://localhost:5000/officer/dashboard` |
| **Field Worker (Roads)** | Road Repair Crew | `worker@smartcivic.com` | `smartcivic123` | Ward 1 | `http://localhost:5000/worker/dashboard` |
| **Field Worker (Electrical)**| Electrical Crew | `worker2@smartcivic.com` | `smartcivic123` | Ward 1 | `http://localhost:5000/worker/dashboard` |
| **Vision Test Citizen** | Vision Test Citizen | `vision_citizen@smartcivic.com` | `smartcivic123` | Ward 1 | `http://localhost:5000/citizen/dashboard` |
| **Vision Test Officer** | Vision Test Officer | `vision_officer@smartcivic.com` | `smartcivic123` | All Wards (`all`) | `http://localhost:5000/officer/dashboard` |
| **Vision Test Worker** | Vision Test Worker | `vision_worker@smartcivic.com` | `smartcivic123` | Ward 1 | `http://localhost:5000/worker/dashboard` |

### Staff Registration Invite Code
To register new staff (`officer` or `worker`) via the registration page (`/register`), use:
```text
ADMIN_INVITE_CODE: SMARTCIVIC-ADMIN-2025
```
*(Without this invite code, officer and worker self-registration will be blocked).*

---

## 2. System Requirements & Prerequisites

1. **Python 3.10+** installed and added to `PATH`.
2. **MongoDB** service running locally on port `27017`:
   - Connection URI: `mongodb://127.0.0.1:27017/smartcivic`
   - Check if running in PowerShell: `Get-Service MongoDB` (or `mongod --version`)
3. **Node.js & npm** (v18+) *(Required only if running the Expo mobile app)*.

---

## 3. How to Run the Program from Terminal

### Step 1: Open Terminal in Project Directory
Navigate to the root directory where `run.py` is located:
```powershell
cd "c:\Users\Muthaheer\Desktop\main project\code 1"
```

---

### Step 2: (Optional) Activate Virtual Environment
If using a virtual environment:
- **Windows PowerShell:**
  ```powershell
  .\venv\Scripts\Activate.ps1
  ```
- **Windows Command Prompt (CMD):**
  ```cmd
  venv\Scripts\activate.bat
  ```
- **Linux / macOS:**
  ```bash
  source venv/bin/activate
  ```

---

### Step 3: Install Dependencies
Ensure all pinned packages are installed:
```powershell
pip install -r requirements.txt
```

---

### Step 4: Verify Environment Configuration (`.env`)
Ensure a `.env` file exists in the project root with the following minimal variables:
```ini
SECRET_KEY=smartcivic-super-secret-key-2025-production-grade-sec
JWT_SECRET=smartcivic-jwt-token-secret-key-2025-auth-string-x
JWT_SECRET_KEY=smartcivic-jwt-token-secret-key-2025-auth-string-x
MONGO_URI=mongodb://127.0.0.1:27017/smartcivic
COOKIE_SECURE=false
FLASK_ENV=development
ADMIN_INVITE_CODE=SMARTCIVIC-ADMIN-2025
```

---

### Step 5: Setup Database Indexes & Seed Default Data

1. **Build Database Indexes:**
   ```powershell
   python setup_indexes.py
   ```

2. **Seed Default Users and Complaints:**
   - **Windows PowerShell:**
     ```powershell
     $env:SEED_PASSWORD="smartcivic123"
     python seed_plus.py
     ```
   - **Windows CMD:**
     ```cmd
     set SEED_PASSWORD=smartcivic123
     python seed_plus.py
     ```
   - **Linux / macOS / Bash:**
     ```bash
     SEED_PASSWORD="smartcivic123" python seed_plus.py
     ```

---

### Step 6: Start the Application Server

#### Option A: Development Server (Default)
Runs Flask with Werkzeug and Socket.IO on port `5000`:
```powershell
python run.py
```
Or specify host and port explicitly:
```powershell
python run.py --host 127.0.0.1 --port 5000
```

#### Option B: Production Server (Waitress on Windows)
Runs production-grade multi-threaded WSGI server (Waitress):
```powershell
python run.py --prod
```

Once running, the terminal will display:
```text
==========================================================================
                    SMARTCIVIC+ SYSTEM STARTUP                            
==========================================================================
 [DB STATUS]  MongoDB Connected | Users | Complaints Registered
 [FEATURES]   Auth, Citizen Portal, Worker Ops, Officer Command, GIS Maps
 [AI ENGINE]  Gemini API + Rule-based NLP Triage & Vision Fallback
 [SECURITY]   JWT Cookies (HttpOnly), RBAC Enforcement, CSP Headers
 --------------------------------------------------------------------------
 [SERVER]     Flask/Werkzeug + Socket.IO (DEV) (DEVELOPMENT mode)
 [*] Server Running at: http://127.0.0.1:5000
 [*] Application Logs:  logs/smartcivic.log
 [*] Press Ctrl+C to stop the server
==========================================================================
```

---

## 4. Web Application URLs

Open your web browser and navigate to:

| Page | URL | Description |
|:---|:---|:---|
| **Home / Redirection** | [http://localhost:5000/](http://localhost:5000/) | Redirects to role dashboard if logged in, else `/login` |
| **Login Page** | [http://localhost:5000/login](http://localhost:5000/login) | Unified sign-in for Citizens, Officers, and Workers |
| **Register Page** | [http://localhost:5000/register](http://localhost:5000/register) | Account registration (use invite code for staff) |
| **Citizen Portal** | [http://localhost:5000/citizen/dashboard](http://localhost:5000/citizen/dashboard) | Submit issues, track history, community corroborate |
| **Ward Verification** | [http://localhost:5000/citizen/verify-ward](http://localhost:5000/citizen/verify-ward) | Resident ward residency document upload |
| **Officer Command** | [http://localhost:5000/officer/dashboard](http://localhost:5000/officer/dashboard) | Triage complaints, assign field workers, review proof |
| **Worker Dashboard** | [http://localhost:5000/worker/dashboard](http://localhost:5000/worker/dashboard) | Assigned tasks, OSRM turn navigation, resolution proof |
| **Public Live Map** | [http://localhost:5000/map](http://localhost:5000/map) | Citywide interactive GIS issue map |
| **Transparency** | [http://localhost:5000/transparency](http://localhost:5000/transparency) | Ward SLA metrics and public resolution statistics |
| **Health Check API** | [http://localhost:5000/api/health](http://localhost:5000/api/health) | System health and database connectivity JSON |

---

## 5. How to Run the Mobile App (React Native / Expo)

If you are running the mobile client:
```powershell
# 1. Enter the mobile directory
cd smartcivic-mobile

# 2. Install mobile dependencies
npm install

# 3. Start Expo development server
npx expo start
```
- Press `a` in the terminal to launch the **Android Emulator**.
- Press `w` to open the **Web Preview**.
- Scan the printed QR code with the **Expo Go** mobile app on a physical Android device.

---

## 6. How to Run Automated Tests

To verify that the application and security controls are operating correctly:

### 1. Run Complete Core Test Suite (156 Tests)
```powershell
pytest test_smartcivic.py -v
```

### 2. Run Pre-Release Hardening Tests (Default-Deny, Retention, CORS, Attacks)
```powershell
pytest tests/test_default_deny.py tests/test_verification_doc_retention.py tests/test_cors_prerelease.py tests/test_stage1_attack_uploads.py -v
```

### 3. Run Live End-to-End Verification Check
*(Make sure `python run.py` is running in another terminal window first)*
```powershell
python test_e2e_verification.py
```

---

## 7. Useful Troubleshooting Commands

- **Port 5000 already in use:**
  ```powershell
  # Find PID using port 5000
  Get-NetTCPConnection -LocalPort 5000 | Select-Object OwningProcess
  # Stop the process
  Stop-Process -Id <PID> -Force
  ```

- **Reset database cleanly:**
  ```powershell
  $env:SEED_PASSWORD="smartcivic123"
  python seed_plus.py
  python setup_indexes.py
  ```

- **Inspect live application log file:**
  ```powershell
  Get-Content -Path logs/smartcivic.log -Tail 50 -Wait
  ```

