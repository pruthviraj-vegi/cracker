/**
 * Reusable Select-to-Toggle Component with Fluid Sliding Pill Indicator
 * Automatically turns any <select class="select-toggle"> into a segmented toggle button group.
 */

(function () {
  'use strict';

  // Common icon mappings for quick auto-discovery
  const ICON_MAP = {
    cash: 'fas fa-money-bill-wave',
    credit: 'fas fa-credit-card',
    upi: 'fas fa-mobile-alt',
    card: 'fas fa-credit-card',
    online: 'fas fa-globe',
    cheque: 'fas fa-money-check-alt',
    bank: 'fas fa-university',
    transfer: 'fas fa-exchange-alt',
    gst_applicable: 'fas fa-file-invoice-dollar',
    non_gst: 'fas fa-receipt',
    gst: 'fas fa-file-invoice-dollar',
    local: 'fas fa-store',
    cgst: 'fas fa-calculator',
    igst: 'fas fa-percentage',
    yes: 'fas fa-check',
    no: 'fas fa-times',
    active: 'fas fa-check-circle',
    inactive: 'fas fa-ban',
    open: 'fas fa-folder-open',
    closed: 'fas fa-folder',
    archived: 'fas fa-archive',
    pending: 'fas fa-clock',
    completed: 'fas fa-check-double',
    user: 'fas fa-user'
  };

  function getOptionIcon(option, select) {
    if (option.dataset.icon) {
      return option.dataset.icon;
    }
    const key = (option.value + ' ' + option.text).toLowerCase();
    for (const [name, iconClass] of Object.entries(ICON_MAP)) {
      if (key.includes(name)) {
        return iconClass;
      }
    }
    if (select && select.name && (select.name.includes('sold_by') || select.name.includes('user') || select.name.includes('created_by'))) {
      return 'fas fa-user';
    }
    if (select && select.dataset.defaultIcon) {
      return select.dataset.defaultIcon;
    }
    return '';
  }

  function initSelectToggle(select) {
    if (!select || select.dataset.toggleInitialized === 'true') {
      return;
    }

    select.dataset.toggleInitialized = 'true';
    select.style.display = 'none';

    const wrapper = document.createElement('div');
    wrapper.className = 'segmented-toggle-wrapper';

    const group = document.createElement('div');
    group.className = 'segmented-toggle-group';
    group.setAttribute('role', 'group');
    if (select.id) {
      group.setAttribute('data-target-select', select.id);
    }

    // Create the fluid sliding indicator element
    const indicator = document.createElement('div');
    indicator.className = 'segmented-toggle-indicator';
    group.appendChild(indicator);

    function updateIndicatorPosition(animate = true) {
      const activeBtn = group.querySelector('.segmented-toggle-btn.active');
      if (activeBtn && group.offsetWidth > 0) {
        const left = activeBtn.offsetLeft;
        const width = activeBtn.offsetWidth;

        if (!animate) {
          indicator.style.transition = 'none';
        } else {
          indicator.style.transition = '';
        }

        indicator.style.width = width + 'px';
        indicator.style.transform = 'translateX(' + left + 'px)';
        indicator.style.opacity = '1';

        if (!animate) {
          // Re-enable transition on next tick
          requestAnimationFrame(() => {
            indicator.style.transition = '';
          });
        }
      } else {
        indicator.style.opacity = '0';
      }
    }

    function getValidOptions() {
      return Array.from(select.options).filter(function (opt) {
        return opt.value && opt.value.trim() !== '' && !opt.text.includes('---');
      });
    }

    function renderButtons() {
      // Remove existing buttons while keeping the indicator
      const existingBtns = group.querySelectorAll('.segmented-toggle-btn');
      existingBtns.forEach(btn => btn.remove());

      const isSelectDisabled = select.disabled;
      const validOptions = getValidOptions();

      validOptions.forEach(function (option) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'segmented-toggle-btn';
        btn.setAttribute('data-value', option.value);

        if (option.selected || select.value === option.value) {
          btn.classList.add('active');
        }

        if (isSelectDisabled || option.disabled) {
          btn.disabled = true;
          btn.classList.add('disabled');
        }

        const iconClass = getOptionIcon(option, select);
        if (iconClass) {
          const icon = document.createElement('i');
          icon.className = iconClass;
          btn.appendChild(icon);
        }

        const span = document.createElement('span');
        span.textContent = option.text || option.value;
        btn.appendChild(span);

        btn.addEventListener('click', function (e) {
          e.preventDefault();
          if (btn.disabled || btn.classList.contains('disabled')) {
            return;
          }

          if (select.value !== option.value) {
            select.value = option.value;
            // Trigger native change event
            select.dispatchEvent(new Event('change', { bubbles: true }));
            // Trigger jQuery change event if available
            if (window.jQuery) {
              window.jQuery(select).trigger('change');
            }
          }
          syncActiveState(true);
        });

        group.appendChild(btn);
      });

      requestAnimationFrame(() => {
        updateIndicatorPosition(false);
      });
    }

    function syncActiveState(animate = true) {
      const currentVal = select.value;
      const isSelectDisabled = select.disabled;
      const validOptions = getValidOptions();

      const buttons = group.querySelectorAll('.segmented-toggle-btn');
      buttons.forEach(function (btn, index) {
        const option = validOptions[index];
        const val = btn.getAttribute('data-value');

        if (val === currentVal) {
          btn.classList.add('active');
        } else {
          btn.classList.remove('active');
        }

        const isOptionDisabled = option ? option.disabled : false;
        if (isSelectDisabled || isOptionDisabled) {
          btn.disabled = true;
          btn.classList.add('disabled');
        } else {
          btn.disabled = false;
          btn.classList.remove('disabled');
        }
      });

      updateIndicatorPosition(animate);
    }

    renderButtons();

    // Insert wrapper in DOM right after select
    if (select.parentNode) {
      select.parentNode.insertBefore(wrapper, select.nextSibling);
      wrapper.appendChild(group);
    }

    // Initial positioning after DOM layout settles
    requestAnimationFrame(() => {
      updateIndicatorPosition(false);
    });

    // ResizeObserver to keep indicator aligned when window/container resizes
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => {
        updateIndicatorPosition(false);
      });
      ro.observe(group);
    } else {
      window.addEventListener('resize', () => updateIndicatorPosition(false));
    }

    // Listen for programmatic or external changes to select
    select.addEventListener('change', () => syncActiveState(true));

    // Observer for option modifications or disabled state changes
    const observer = new MutationObserver(function () {
      syncActiveState(true);
    });
    observer.observe(select, { attributes: true, childList: true, subtree: true });
  }

  function initAllSelectToggles(context) {
    const root = context || document;
    const selects = root.querySelectorAll('select.select-toggle, select.toggle-select, select[data-toggle="select"]');
    selects.forEach(initSelectToggle);
  }

  // Export globally
  window.initSelectToggles = initAllSelectToggles;
  window.initSelectToggle = initSelectToggle;

  // Auto initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      initAllSelectToggles();
    });
  } else {
    initAllSelectToggles();
  }
})();
