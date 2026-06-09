/* SmartCivic - Voting Helpers */

const VotePanel = {
  cast: async function(issueId, voteType, severityVal) {
    if (!Auth.isLoggedIn()) {
      showToast("Please log in to vote", "error");
      window.location.href = '/login';
      return;
    }
    
    const res = await apiFetch('/api/votes/cast', {
      method: 'POST',
      body: JSON.stringify({
        issue_id: issueId,
        vote_type: voteType,
        severity_vote: severityVal
      })
    });
    
    if (res?.success) {
      showToast("Vote cast successfully!", "success");
      VotePanel.refreshStats(issueId);
    } else if (res) {
      showToast(res.message, "error");
    }
  },

  refreshStats: async function(issueId) {
    const statsContainer = document.getElementById('vote-stats-container');
    if (!statsContainer) return;
    
    const res = await apiFetch(`/api/votes/issue/${issueId}`);
    if (res?.success) {
      const data = res.data;
      
      let distributionHtml = '';
      Object.entries(data.severity_distribution).forEach(([sev, count]) => {
        const percentage = data.total > 0 ? (count / data.total) * 100 : 0;
        distributionHtml += `
          <div style="margin-bottom:8px;">
            <div style="display:flex; justify-content:space-between; font-size:0.8rem; margin-bottom:2px;">
              <span>${'★'.repeat(sev)}</span>
              <span>${count} votes (${Math.round(percentage)}%)</span>
            </div>
            <div style="height:6px; background:#e2e8f0; border-radius:3px; overflow:hidden;">
              <div style="height:100%; width:${percentage}%; background:var(--primary); border-radius:3px;"></div>
            </div>
          </div>
        `;
      });

      statsContainer.innerHTML = `
        <div class="card" style="margin-top:20px;">
          <h3 style="margin-bottom:15px;" data-i18n="score_label">Community Validation Statistics</h3>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px; text-align:center;">
            <div style="background:var(--success-light); color:var(--success); padding:10px; border-radius:var(--radius-sm); font-weight:bold;">
              Confirmations: ${data.confirm_count}
            </div>
            <div style="background:var(--danger-light); color:var(--danger); padding:10px; border-radius:var(--radius-sm); font-weight:bold;">
              Denials: ${data.deny_count}
            </div>
          </div>
          <div>
            <h4 style="margin-bottom:10px; font-size:0.9rem;">Severity Distribution</h4>
            ${distributionHtml}
          </div>
          ${data.user_has_voted ? `
            <div style="margin-top:15px; text-align:center; font-weight:500; font-size:0.9rem; color:var(--neutral-600)">
              Your vote: <span style="text-transform:uppercase; font-weight:bold; color:${data.user_vote_type === 'confirm' ? 'var(--success)' : 'var(--danger)'}">${data.user_vote_type}</span>
            </div>
          ` : ''}
        </div>
      `;
      
      // If translations are loaded
      if (typeof applyTranslations === 'function') {
        applyTranslations();
      }
    }
  }
};
