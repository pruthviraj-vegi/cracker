// ========================================
// BILLING SYSTEM - NOTIFICATION MANAGEMENT
// ========================================

// ── Notification Sound (Web Audio API) ──────────────────
const NotificationSound = (function() {
  let audioCtx = null;
  let activeOscCount = 0;

  async function getContext() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') await audioCtx.resume();
    return audioCtx;
  }

  async function playTone(freq, duration, type, volume, delay) {
    const ctx = await getContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type || 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(volume || 0.15, ctx.currentTime + (delay || 0));
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + (delay || 0) + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    activeOscCount++;
    osc.addEventListener('ended', () => {
      activeOscCount--;
      if (activeOscCount <= 0 && audioCtx && audioCtx.state === 'running') {
        audioCtx.suspend();
      }
    });
    osc.start(ctx.currentTime + (delay || 0));
    osc.stop(ctx.currentTime + (delay || 0) + duration);
  }

  return {
    success: function() {
      playTone(523, 0.15, 'sine', 0.12, 0);     // C5
      playTone(659, 0.2, 'sine', 0.12, 0.12);    // E5
      playTone(784, 0.25, 'sine', 0.10, 0.22);   // G5
    },
    error: function() {
      playTone(330, 0.2, 'square', 0.08, 0);     // E4
      playTone(262, 0.3, 'square', 0.06, 0.15);   // C4
    },
    info: function() {
      playTone(587, 0.2, 'sine', 0.10, 0);       // D5
    },
    warning: function() {
      playTone(440, 0.15, 'triangle', 0.10, 0);  // A4
      playTone(440, 0.15, 'triangle', 0.10, 0.2); // A4 repeat
    }
  };
})();

// ── Toast Stacking Helper ──────────────────────────────
function updateToastStack() {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const cards = Array.from(container.querySelectorAll('.toast-card:not(.toast-hiding)'));
  const count = cards.length;
  container.classList.toggle('toast-stacked', count > 1);
  cards.forEach((card, index) => {
    const revIndex = count - 1 - index;
    card.style.setProperty('--stack-rev-index', revIndex);
  });
}

// ── Toast Notification Display ──────────────────────────
function showNotification(message, type = 'info', duration = 3500) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const icons = {
    success: 'fa-check-circle',
    error: 'fa-times-circle',
    danger: 'fa-times-circle',
    warning: 'fa-exclamation-triangle',
    info: 'fa-info-circle'
  };
  const iconClass = icons[type] || icons.info;
  const normalizedType = type === 'danger' ? 'error' : type;

  const toast = document.createElement('div');
  toast.className = `toast-card toast-${normalizedType}`;
  toast.setAttribute('role', 'alert');

  const escapedMsg = typeof escapeHtml === 'function' ? escapeHtml(message) : message;

  toast.innerHTML = `
    <div class="toast-icon-wrapper">
      <i class="fas ${iconClass}"></i>
    </div>
    <div class="toast-body">
      <div class="toast-message">${escapedMsg}</div>
    </div>
    <button type="button" class="toast-close toast-close-btn" aria-label="Close">
      <i class="fas fa-times"></i>
    </button>
    <div class="toast-progress-bar toast-progress-${normalizedType}" style="animation-duration: ${duration}ms;"></div>
  `;

  try {
    if (typeof NotificationSound !== 'undefined') {
      const soundKey = normalizedType === 'error' ? 'error' : (NotificationSound[normalizedType] ? normalizedType : 'info');
      NotificationSound[soundKey]();
    }
  } catch(e) { /* Audio non-blocking */ }

  container.appendChild(toast);
  updateToastStack();

  const dismiss = () => {
    if (toast.classList.contains('toast-hiding')) return;
    toast.classList.add('toast-hiding');
    updateToastStack();
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
        updateToastStack();
      }
    }, 350);
  };

  const closeBtn = toast.querySelector('.toast-close, .toast-close-btn');
  if (closeBtn) closeBtn.addEventListener('click', dismiss);
  setTimeout(dismiss, duration);
}

// Attach to window scope
window.showNotification = showNotification;
window.NotificationSound = NotificationSound;

// Flush any pending notifications queued before this script finished loading
if (Array.isArray(window._pendingNotifications) && window._pendingNotifications.length > 0) {
  const pendingQueue = window._pendingNotifications.slice();
  window._pendingNotifications = [];
  pendingQueue.forEach(function(item) {
    if (item && item.message) {
      showNotification(item.message, item.type, item.duration);
    }
  });
}

// ── Topbar Notification Panel Dropdown ──────────────────
document.addEventListener('DOMContentLoaded', function() {
  if (typeof window.NOTIF_URLS === 'undefined') {
    console.warn("NOTIF_URLS is not defined.");
  }
  const NOTIF_URLS = window.NOTIF_URLS || {};
  const csrfToken = window.csrfToken || '';

  const notifBtn      = document.getElementById('notificationBtn');
  const notifPanel    = document.getElementById('notificationPanel');
  const notifBadge    = document.getElementById('notificationBadge');
  const notifBody     = document.getElementById('notificationPanelBody');
  const markAllBtn    = document.getElementById('markAllReadBtn');
  const notifWrapper  = document.getElementById('notificationWrapper');

  // Update badge count
  function updateNotifBadge() {
    if (!NOTIF_URLS.count) return;
    fetch(NOTIF_URLS.count)
      .then(function(res) { return res.json(); })
      .then(function(data) {
        var count = data.unread_count || 0;
        if (count > 0) {
          notifBadge.textContent = count > 99 ? '99+' : count;
          notifBadge.classList.remove('d-none');
          notifBadge.style.display = 'flex';
          notifBadge.classList.remove('badge-pop');
          void notifBadge.offsetWidth;
          notifBadge.classList.add('badge-pop');
        } else {
          notifBadge.classList.add('d-none');
          notifBadge.style.display = 'none';
        }
      }).catch(console.error);
  }

  // Render notification items
  function renderNotifications(notifications) {
    if (!notifications.length) {
      notifBody.innerHTML =
        '<div class="notification-panel-empty">' +
        '<i class="fas fa-bell-slash"></i>' +
        '<p>No notifications yet</p>' +
        '</div>';
      return;
    }
    let html = '';
    notifications.forEach(function(n, idx) {
      const readClass = n.is_read ? 'is-read' : '';
      const safeLabel = typeof escapeHtml === 'function' ? escapeHtml(n.action_label) : n.action_label;
      const safeUrl = typeof escapeAttr === 'function' ? escapeAttr(n.action_url) : n.action_url;
      const actionBtn = n.action_url && n.action_label
        ? '<a href="' + safeUrl + '" class="notif-action-btn">' + safeLabel + '</a>'
        : '';
      const safeColor = typeof escapeAttr === 'function' ? escapeAttr(n.color || '#4f46e5') : '#4f46e5';
      const safeIcon = typeof escapeAttr === 'function' ? escapeAttr(n.icon || 'fa-bell') : 'fa-bell';
      const safeTitle = typeof escapeHtml === 'function' ? escapeHtml(n.title) : n.title;
      const safeTime = typeof escapeHtml === 'function' ? escapeHtml(n.created_at) : n.created_at;
      const safeMsg = typeof escapeHtml === 'function' ? escapeHtml(n.message) : n.message;
      const safeBadgeLabel = typeof escapeHtml === 'function' ? escapeHtml(n.badge_label) : n.badge_label;

      html +=
        '<div class="notif-item ' + readClass + '" data-id="' + n.id + '" style="--item-index: ' + idx + ';">' +
        '  <div class="notif-icon" style="color:' + safeColor + '">' +
        '    <i class="fas ' + safeIcon + '"></i>' +
        '  </div>' +
        '  <div class="notif-content">' +
        '    <div class="notif-header-row">' +
        '      <div class="notif-title">' + safeTitle + '</div>' +
        '      <span class="notif-time">' + safeTime + '</span>' +
        '    </div>' +
        '    <div class="notif-message">' + safeMsg + '</div>' +
        '    <div class="notif-meta">' +
        '      <span class="notif-badge-label">' + safeBadgeLabel + '</span>' +
        '    </div>' +
        '    ' + actionBtn +
        '  </div>' +
        '</div>';
    });
    notifBody.innerHTML = html;

    // Click to mark as read
    notifBody.querySelectorAll('.notif-item:not(.is-read)').forEach(function(el) {
      el.addEventListener('click', function() {
        const id = el.dataset.id;
        fetch(NOTIF_URLS.markRead.replace('{id}', id), {
          method: 'POST',
          headers: {'X-CSRFToken': csrfToken}
        }).then(() => {
            el.classList.add('is-read');
            updateNotifBadge();
        }).catch(console.error);
      });
    });
  }

  // Fetch and show notifications
  function loadNotifications() {
    notifBody.innerHTML =
      '<div class="notification-panel-loading">' +
      '<i class="fas fa-spinner fa-spin"></i> Loading...' +
      '</div>';
    fetch(NOTIF_URLS.list)
      .then(res => {
        if (!res.ok) throw new Error('Network failure');
        return res.json();
      })
      .then(data => {
        renderNotifications(data.notifications || []);
      })
      .catch(() => {
        notifBody.innerHTML =
          '<div class="notification-panel-empty">' +
          '<i class="fas fa-exclamation-triangle"></i>' +
          '<p>Failed to load</p>' +
          '</div>';
      });
  }

  // Toggle panel
  if (notifBtn) {
    notifBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      const isOpen = notifPanel.classList.toggle('open');
      if (isOpen) loadNotifications();
    });
  }

  // Mark all read
  if (markAllBtn) {
    markAllBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      fetch(NOTIF_URLS.markAllRead, {
        method: 'POST',
        headers: {'X-CSRFToken': csrfToken}
      }).then(() => {
          notifBody.querySelectorAll('.notif-item').forEach(function(el) {
            el.classList.add('is-read');
          });
          updateNotifBadge();
          showNotification('All notifications marked as read', 'success');
      }).catch(console.error);
    });
  }

  // Close panel on outside click
  document.addEventListener('click', function(e) {
    if (notifWrapper && !notifWrapper.contains(e.target)) {
      notifPanel.classList.remove('open');
    }
  });
});
