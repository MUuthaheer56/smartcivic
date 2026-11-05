/**
 * SmartCivic — Internationalization (Kannada/English) & Voice Speech Recognition
 * Provides bilingual localized strings, validation for Kannada input,
 * and browser speech-to-text recognition interface.
 */

const SmartCivicTranslations = {
  en: {
    // Actions & Form
    submit_complaint: "Submit Complaint",
    report_issue: "Report Civic Issue",
    description: "Issue Description",
    description_placeholder: "Describe the civic issue in detail (e.g. pothole location, severity, nearby landmarks)...",
    category: "Category",
    select_category: "Select Category",
    location: "Location",
    upload_photo: "Upload Photo",
    voice_input: "Voice Input",
    listening: "Listening... speak now in English or Kannada",
    stop_listening: "Stop Listening",
    submitting: "Submitting...",

    // Categories
    roads: "Roads & Footpaths",
    water: "Water Supply",
    electricity: "Electricity & Streetlights",
    sanitation: "Sanitation & Solid Waste",
    drainage: "Stormwater Drainage",
    other: "Other Civic Services",

    // Statuses & Badges
    p0_emergency: "P0 Emergency Fast-Lane",
    status_submitted: "Submitted",
    status_in_progress: "In Progress",
    status_work_completed: "Work Completed",
    status_verified: "Verified & Resolved",
    status_reopened: "Reopened",

    // Evidence Badges (Rule R7)
    evidence_detected: "Detected (Image)",
    evidence_inferred: "Inferred (AI Analysis)",
    evidence_verified: "Verified (Human Confirmed)",

    // Metrics & Framing
    expected_reporting_volume: "Expected Reporting Volume",
    complaint_density: "Complaint Density",
    sla_countdown: "SLA Countdown",
    civic_score: "CivicScore",
    ward_health: "Ward Health Index"
  },

  kn: {
    // Actions & Form
    submit_complaint: "ದೂರು ಸಲ್ಲಿಸಿ",
    report_issue: "ನಾಗರಿಕ ಸಮಸ್ಯೆ ವರದಿ ಮಾಡಿ",
    description: "ಸಮಸ್ಯೆಯ ವಿವರಣೆ",
    description_placeholder: "ಸಮಸ್ಯೆಯ ಬಗ್ಗೆ ವಿವರವಾಗಿ ತಿಳಿಸಿ (ಉದಾ: ರಸ್ತೆ ಗುಂಡಿ, ಸ್ಥಳ, ನೀರಿನ ಸೋರಿಕೆ)...",
    category: "ವಿಭಾಗ",
    select_category: "ವಿಭಾಗ ಆಯ್ಕೆಮಾಡಿ",
    location: "ಸ್ಥಳ",
    upload_photo: "ಭಾವಚಿತ್ರ ಅಪ್‌ಲೋಡ್ ಮಾಡಿ",
    voice_input: "ಧ್ವನಿ ಮೂಲಕ ದಾಖಲಿಸಿ",
    listening: "ಕೇಳಿಸಿಕೊಳ್ಳುತ್ತಿದೆ... ಕನ್ನಡ ಅಥವಾ ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಮಾತನಾಡಿ",
    stop_listening: "ನಿಲ್ಲಿಸಿ",
    submitting: "ಸಲ್ಲಿಸಲಾಗುತ್ತಿದೆ...",

    // Categories
    roads: "ರಸ್ತೆಗಳು ಮತ್ತು ಪಾದಚಾರಿ ಮಾರ್ಗ",
    water: "ಕುಡಿಯುವ ನೀರು ಸರಬರಾಜು",
    electricity: "ವಿದ್ಯುತ್ ಮತ್ತು ಬೀದಿ ದೀಪಗಳು",
    sanitation: "ಸ್ವಚ್ಛತೆ ಮತ್ತು ಘನತ್ಯಾಜ್ಯ",
    drainage: "ಮಳೆನೀರು ಚರಂಡಿ",
    other: "ಇತರ ನಾಗರಿಕ ಸೇವೆಗಳು",

    // Statuses & Badges
    p0_emergency: "P0 ತುರ್ತು ಸೇವೆ",
    status_submitted: "ದಾಖಲಾಗಿದೆ",
    status_in_progress: "ಪ್ರಗತಿಯಲ್ಲಿದೆ",
    status_work_completed: "ಕಾರ್ಯ ಪೂರ್ಣಗೊಂಡಿದೆ",
    status_verified: "ದೃಢೀಕರಿಸಿ ಮುಕ್ತಾಯಗೊಳಿಸಲಾಗಿದೆ",
    status_reopened: "ಮರುಪರಿಶೀಲನೆಗೆ ಕಳುಹಿಸಲಾಗಿದೆ",

    // Evidence Badges (Rule R7)
    evidence_detected: "ಚಿತ್ರದಲ್ಲಿ ಗುರುತಿಸಲಾಗಿದೆ",
    evidence_inferred: "ಅಂದಾಜಿಸಲಾಗಿದೆ (AI)",
    evidence_verified: "ದೃಢೀಕರಿಸಲಾಗಿದೆ (ಮಾನವ)",

    // Metrics & Framing
    expected_reporting_volume: "ನಿರೀಕ್ಷಿತ ದೂರುಗಳ ಪ್ರಮಾಣ",
    complaint_density: "ದೂರುಗಳ ಸಾಂದ್ರತೆ",
    sla_countdown: "SLA ಉಳಿದ ಸಮಯ",
    civic_score: "ಸಿವಿಕ್ ಸ್ಕೋರ್",
    ward_health: "ವಾರ್ಡ್ ಆರೋಗ್ಯ ಸೂಚ್ಯಂಕ"
  }
};

class SmartCivicI18n {
  constructor() {
    this.currentLang = localStorage.getItem('smartcivic_lang') || 'en';
  }

  getLang() {
    return this.currentLang;
  }

  setLang(lang) {
    if (SmartCivicTranslations[lang]) {
      this.currentLang = lang;
      localStorage.setItem('smartcivic_lang', lang);
      this.applyTranslations();
    }
  }

  t(key) {
    const dict = SmartCivicTranslations[this.currentLang] || SmartCivicTranslations.en;
    return dict[key] || SmartCivicTranslations.en[key] || key;
  }

  validateKannada(text) {
    if (!text || typeof text !== 'string') return false;
    // Kannada Unicode Block: \u0C80 - \u0CFF
    const kannadaRegex = /[\u0C80-\u0CFF]/;
    return kannadaRegex.test(text);
  }

  applyTranslations() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (key) {
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
          el.placeholder = this.t(key);
        } else {
          el.textContent = this.t(key);
        }
      }
    });
  }
}

class SmartCivicSpeech {
  constructor(i18nInstance) {
    this.i18n = i18nInstance || new SmartCivicI18n();
    const SpeechClass = window.SpeechRecognition || window.webkitSpeechRecognition;
    this.recognition = SpeechClass ? new SpeechClass() : null;
    this.isRecording = false;

    if (this.recognition) {
      this.recognition.continuous = false;
      this.recognition.interimResults = false;
    }
  }

  isSupported() {
    return this.recognition !== null;
  }

  start(onResultCallback, onErrorCallback, onEndCallback) {
    if (!this.recognition) {
      if (onErrorCallback) onErrorCallback("Speech recognition not supported in this browser");
      return;
    }

    // Set recognition language based on active UI language
    this.recognition.lang = this.i18n.getLang() === 'kn' ? 'kn-IN' : 'en-IN';

    this.recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      this.isRecording = false;
      if (onResultCallback) onResultCallback(transcript);
    };

    this.recognition.onerror = (event) => {
      this.isRecording = false;
      if (onErrorCallback) onErrorCallback(event.error);
    };

    this.recognition.onend = () => {
      this.isRecording = false;
      if (onEndCallback) onEndCallback();
    };

    try {
      this.recognition.start();
      this.isRecording = true;
    } catch (err) {
      this.isRecording = false;
      if (onErrorCallback) onErrorCallback(err.message);
    }
  }

  stop() {
    if (this.recognition && this.isRecording) {
      this.recognition.stop();
      this.isRecording = false;
    }
  }
}

// Global instances
window.smartCivicI18n = new SmartCivicI18n();
window.smartCivicSpeech = new SmartCivicSpeech(window.smartCivicI18n);

