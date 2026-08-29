/* SmartCivic — AI Intelligence Hub Panel */

const AIInsights = {
  communityId: null,

  init: async function() {
    const user = Auth.getUser();
    if (!user || user.role !== 'authority') {
      window.location.href = '/login';
      return;
    }
    AIInsights.communityId = user.community_id;
    await Promise.all([
      AIInsights.loadTrustScore(),
      AIInsights.loadAnomalies(),
      AIInsights.loadDrainRisk()
    ]);
  },

  loadTrustScore: async function() {
    const container = document.getElementById('trust-score-container');
    const res = await apiFetch(`/api/ai/trust-score/${AIInsights.communityId}`);
    if (!res?.success) { container.innerHTML = '<p>Could not load trust score.</p>'; return; }
    const d = res.data;
    const gradeColor = { A: 'var(--sc-success)', B: 'var(--sc-info)', C: 'var(--sc-warning)', D: 'var(--sc-danger)' }[d.grade] || 'var(--sc-text-muted)';
    container.innerHTML = `
      <div style="display:grid;grid-template-columns:auto 1fr;gap:24px;align-items:center;">
        <div style="width:100px;height:100px;border-radius:50%;background:conic-gradient(${gradeColor} ${d.trust_score * 3.6}deg, var(--sc-border) 0);display:flex;align-items:center;justify-content:center;">
          <div style="width:80px;height:80px;background:var(--sc-surface);border-radius:50%;display:flex;flex-direction:column;align-items:center;justify-content:center;">
            <span style="font-size:1.4rem;font-weight:800;color:${gradeColor};">${d.grade}</span>
            <span style="font-size:0.7rem;color:var(--sc-text-muted);">${d.trust_score}/100</span>
          </div>
        </div>
        <div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:0.85rem;">
            <div>SLA Compliance: <strong>${d.components.sla_compliance_rate}%</strong></div>
            <div>Resolution Rate: <strong>${d.components.resolution_rate}%</strong></div>
            <div>Participation: <strong>${d.components.participation_rate}%</strong></div>
            <div>Recurrence Penalty: <strong style="color:var(--sc-danger)">${d.components.recurrence_penalty}%</strong></div>
          </div>
        </div>
      </div>
    `;
  },

  loadAnomalies: async function() {
    const container = document.getElementById('anomaly-container');
    const res = await apiFetch(`/api/ai/anomalies/${AIInsights.communityId}?lookback_days=30`);
    if (!res?.success) { container.innerHTML = '<p>Could not load anomaly data.</p>'; return; }
    const anomalies = res.data;
    if (!anomalies.length) {
      container.innerHTML = '<div style="color:var(--sc-success);font-weight:600;">✓ No reporting anomalies detected.</div>';
      return;
    }
    container.innerHTML = anomalies.map(a => `
      <div style="padding:12px 16px;border-left:4px solid ${a.severity === 'HIGH' ? 'var(--sc-danger)' : 'var(--sc-warning)'};background:${a.severity === 'HIGH' ? 'var(--sc-danger-soft)' : 'var(--sc-warning-soft)'};border-radius:0 8px 8px 0;margin-bottom:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <strong style="text-transform:capitalize;">${a.category}</strong>
          <span style="font-size:0.75rem;font-weight:700;color:${a.severity === 'HIGH' ? 'var(--sc-danger)' : 'var(--sc-warning)'};">${a.severity} · Z=${a.z_score}</span>
        </div>
        <p style="font-size:0.82rem;color:var(--sc-text-secondary);margin:4px 0 0;">${a.message}</p>
      </div>
    `).join('');
  },

  loadDrainRisk: async function() {
    const container = document.getElementById('drain-risk-container');
    const res = await apiFetch(`/api/ai/drain-risk/${AIInsights.communityId}`);
    if (!res?.success) { container.innerHTML = '<p>Could not load drain risk.</p>'; return; }
    const risks = res.data;
    if (!risks.length) {
      container.innerHTML = '<div style="color:var(--sc-success);font-weight:600;">✓ No drain risks detected near current issues.</div>';
      return;
    }
    container.innerHTML = `<div style="display:grid;gap:10px;">` + risks.map(r => `
      <div style="padding:14px;border:1px solid ${r.alert ? 'var(--sc-danger)' : 'var(--sc-border)'};border-radius:10px;background:${r.alert ? 'var(--sc-danger-soft)' : 'var(--sc-surface)'};">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <strong>${r.drain_name}</strong>
          <span style="font-weight:800;color:${r.alert ? 'var(--sc-danger)' : 'var(--sc-text-muted)'};">${r.risk_score}/100 ${r.alert ? '🚨 ALERT' : ''}</span>
        </div>
        <div style="font-size:0.8rem;color:var(--sc-text-muted);display:flex;gap:16px;">
          <span>🗑️ ${r.complaint_count} nearby complaints</span>
          <span>🌧️ ${Math.round(r.rain_probability_48h * 100)}% rain (48h)</span>
          <span>⚡ Avg severity: ${r.avg_severity}</span>
        </div>
        <div style="margin-top:8px;background:var(--sc-border);border-radius:4px;height:6px;overflow:hidden;">
          <div style="height:100%;width:${r.risk_score}%;background:${r.risk_score >= 60 ? 'var(--sc-danger)' : r.risk_score >= 30 ? 'var(--sc-warning)' : 'var(--sc-success)'};border-radius:4px;"></div>
        </div>
      </div>
    `).join('') + `</div>`;
  },

  validateNoise: async function() {
    const dbSpl = parseFloat(document.getElementById('noise-db').value);
    const zone = document.getElementById('noise-zone').value;
    const isNight = document.getElementById('noise-period').value === 'true';
    const resultDiv = document.getElementById('noise-result');

    if (isNaN(dbSpl)) { showToast('Please enter a valid dB SPL value', 'error'); return; }

    const res = await apiFetch('/api/ai/validate-noise', {
      method: 'POST',
      body: JSON.stringify({ db_spl: dbSpl, zone_type: zone, is_night: isNight })
    });

    if (!res?.success) { showToast(res?.message || 'Validation failed', 'error'); return; }
    const d = res.data;
    const color = d.compliant ? 'var(--sc-success)' : d.excess_db > 15 ? 'var(--sc-danger)' : 'var(--sc-warning)';
    resultDiv.innerHTML = `
      <div style="padding:14px;border:2px solid ${color};border-radius:10px;">
        <div style="font-weight:700;font-size:1rem;color:${color};margin-bottom:8px;">${d.cpcb_status}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;font-size:0.85rem;">
          <div>Measured: <strong>${d.measured_db} dB</strong></div>
          <div>Limit: <strong>${d.limit_db} dB</strong></div>
          <div>Excess: <strong style="color:${color}">+${d.excess_db} dB</strong></div>
          <div>Zone: <strong style="text-transform:capitalize;">${d.zone}</strong></div>
          <div>Period: <strong style="text-transform:capitalize;">${d.period}</strong></div>
          <div>Est. Severity: <strong>${'★'.repeat(d.estimated_severity)}${'☆'.repeat(5 - d.estimated_severity)}</strong></div>
        </div>
      </div>
    `;
  }
};
