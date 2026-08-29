/* SmartCivic - Interactive Onboarding Tour (Vanilla JS) */

const TOUR_STEPS = [
  {
    selector: '#community-score-gauge',
    title: 'Community Score',
    text: 'This shows how well-maintained your community is. Scores drop when issues are reported and rise when they are resolved.'
  },
  {
    selector: '#report-btn',
    title: 'Report an Issue',
    text: 'Click here to report a civic problem near you. Add a photo and drop a pin on the map.'
  },
  {
    selector: '#issue-list-link',
    title: 'Browse Issues',
    text: 'See all issues reported in your community. Vote to confirm or deny reports from your neighbors.'
  },
  {
    selector: '#notif-bell',
    title: 'Notifications',
    text: 'Get real-time updates when your reported issues are validated or resolved.'
  },
  {
    selector: '.reputation-badge',
    title: 'Your Reputation',
    text: 'Earn reputation points by reporting real issues, casting accurate votes, and helping your community.'
  }
];

let currentTourStep = 0;
let tourOverlay = null;

function startTour() {
  const user = Auth.getUser();
  if (!user || user.onboarding_complete) return;
  
  currentTourStep = 0;
  createTourOverlay();
  showTourStep(0);
}

function createTourOverlay() {
  if (document.getElementById('tour-overlay')) return;
  
  tourOverlay = document.createElement('div');
  tourOverlay.id = 'tour-overlay';
  tourOverlay.style.position = 'fixed';
  tourOverlay.style.top = '0';
  tourOverlay.style.left = '0';
  tourOverlay.style.width = '100vw';
  tourOverlay.style.height = '100vh';
  tourOverlay.style.backgroundColor = 'rgba(15, 23, 42, 0.75)';
  tourOverlay.style.zIndex = '9999';
  tourOverlay.style.pointerEvents = 'auto';
  tourOverlay.style.transition = 'all 0.3s ease';
  document.body.appendChild(tourOverlay);
  
  const card = document.createElement('div');
  card.id = 'tour-card';
  card.className = 'card';
  card.style.position = 'absolute';
  card.style.width = '320px';
  card.style.zIndex = '10000';
  card.style.boxShadow = 'var(--shadow-lg)';
  card.style.transition = 'all 0.3s ease';
  
  tourOverlay.appendChild(card);
}

function showTourStep(index) {
  if (index < 0 || index >= TOUR_STEPS.length) {
    endTour();
    return;
  }
  
  currentTourStep = index;
  const step = TOUR_STEPS[index];
  const target = document.querySelector(step.selector);
  const card = document.getElementById('tour-card');
  
  if (!card) return;
  
  card.innerHTML = `
    <h3 style="margin-bottom:8px; color:var(--primary);">${step.title}</h3>
    <p style="font-size:0.9rem; color:var(--neutral-700); margin-bottom:16px;">${step.text}</p>
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <span style="font-size:0.75rem; color:var(--neutral-400)">Step ${index + 1} of ${TOUR_STEPS.length}</span>
      <div style="display:flex; gap:8px;">
        <button class="btn btn-secondary" style="padding:4px 8px; font-size:0.8rem;" onclick="endTour()">Skip</button>
        <button class="btn btn-primary" style="padding:4px 8px; font-size:0.8rem;" onclick="nextTourStep()">${index === TOUR_STEPS.length - 1 ? 'Finish' : 'Next'}</button>
      </div>
    </div>
  `;
  
  if (target) {
    // Scroll target into view
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    
    // Highlight target element using shadow or boundary
    const rect = target.getBoundingClientRect();
    card.style.top = `${rect.bottom + window.scrollY + 12}px`;
    card.style.left = `${Math.min(window.innerWidth - 340, Math.max(20, rect.left + window.scrollX - 100))}px`;
    
    // Ensure card doesn't go offscreen top
    if (rect.bottom + 12 + 180 > window.innerHeight) {
      card.style.top = `${rect.top + window.scrollY - 180}px`;
    }
  } else {
    // Center of screen
    card.style.top = '50%';
    card.style.left = '50%';
    card.style.transform = 'translate(-50%, -50%)';
  }
}

function nextTourStep() {
  showTourStep(currentTourStep + 1);
}

function endTour() {
  if (tourOverlay) {
    tourOverlay.remove();
    tourOverlay = null;
  }
  
  // Call complete api
  apiFetch('/api/auth/onboarding-complete', { method: 'PUT' }).then(res => {
    if (res?.success) {
      const user = Auth.getUser();
      if (user) {
        user.onboarding_complete = true;
        Auth.setSession(Auth.getToken(), user);
      }
      showToast("Onboarding complete! Enjoy SmartCivic.", "success");
    }
  });
}

// Auto start tour from URL parameter check
document.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  if (params.get('start_tour') === 'true') {
    setTimeout(() => {
      // Initialize tour overlay directly bypassing verification status check for demonstration
      currentTourStep = 0;
      createTourOverlay();
      showTourStep(0);
    }, 800);
  } else {
    setTimeout(() => {
      startTour();
    }, 1000);
  }
});

