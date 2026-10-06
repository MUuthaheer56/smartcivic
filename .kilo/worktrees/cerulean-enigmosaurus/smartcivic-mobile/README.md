# SmartCivic v2 — Standalone React Native Mobile Application (Expo)

This is the official mobile application for **SmartCivic v2**, built with React Native and Expo. It allows field workers to receive assigned repair jobs, capture resolution proof with live GPS, and enables citizens to file location-tagged complaints.

---

## 🚀 Quick Setup & Execution

### 1. Install Dependencies
Navigate into the mobile project directory:
```bash
cd smartcivic-mobile
npm install
```

### 2. Configure Backend Local IP Address
When testing on a **physical mobile phone** via Expo Go:
1. Your computer's current IPv4 network address is:
   `10.30.128.225`
2. Launch the app on your phone. In the login screen, set the API server endpoint to:
   ```
   http://10.30.128.225:5000/api
   ```

### 3. Start Expo Development Server
```bash
npx expo start
```
- A QR code will appear in your terminal.
- Open the **Expo Go** app on your physical iPhone or Android device and scan the QR code.

---

## 📱 Features

1. **Dual JWT Bearer Token Authentication**:
   - Logs into Flask backend (`POST /api/auth/login`) and saves JWT token securely using `expo-secure-store`.
2. **Worker Field Task Dashboard**:
   - Queries assigned repair jobs (`GET /api/workers/tasks`).
3. **Camera & GPS Resolution Proof Capture**:
   - Uses `expo-image-picker` to take proof photos on site.
   - Uses `expo-location` to tag exact latitude/longitude coordinates.
   - Posts resolution proof directly to `/api/issues/:id/resolve`.
4. **Citizen Grievance Submission**:
   - File complaints with category selection, before photos, and live GPS tagging (`POST /api/issues`).

---

## 🛠 Packaging Standalone Build (APK / IPA)

To build a standalone APK for Android or IPA for iOS:
```bash
npx eas-cli build --platform android --profile preview
```
