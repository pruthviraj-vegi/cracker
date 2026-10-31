// ========================================
// SIDEBAR JS — Mobile-Only Sidebar Navigation
// At ≤768px, transforms the horizontal .navbar into
// a slide-in vertical sidebar overlay.
// Desktop uses native CSS hover dropdowns from main.css.
// ========================================

(function () {
  'use strict';

  let sidebar, toggleBtn, overlay;

  function initSidebar() {
    sidebar = document.getElementById('sidebar');
    toggleBtn = document.getElementById('sidebarToggle');
    overlay = document.getElementById('sidebarOverlay');

    if (!sidebar || !toggleBtn) return;

    // Hamburger toggle (mobile only)
    toggleBtn.addEventListener('click', function () {
      if (window.innerWidth <= 768) {
        toggleSidebar();
      }
    });

    // Overlay click closes sidebar
    if (overlay) {
      overlay.addEventListener('click', closeSidebar);
    }

    // Accordion dropdowns (mobile only)
    initAccordion();

    // Close sidebar when leaf link clicked (mobile)
    initMobileNavClose();

    // Resize: reset state when going above mobile
    window.addEventListener('resize', function () {
      if (window.innerWidth > 768) {
        resetSidebar();
      }
    });

    // Init on load
    initPageActionsDropdowns();

    // Global: close page-actions dropdown on outside click
    document.addEventListener('click', function (e) {
      if (!e.target.closest('.page-actions')) {
        document.querySelectorAll('.page-actions-dropdown.open').forEach(function (d) {
          d.classList.remove('open');
        });
      }
    });
  }

  function toggleSidebar() {
    if (!sidebar || window.innerWidth > 768) return;

    var isActive = sidebar.classList.toggle('active');
    if (overlay) {
      overlay.classList.toggle('active', isActive);
    }
    document.body.style.overflow = isActive ? 'hidden' : '';
  }

  function closeSidebar() {
    if (!sidebar) return;
    sidebar.classList.remove('active');
    if (overlay) {
      overlay.classList.remove('active');
    }
    document.body.style.overflow = '';
    // Close all dropdowns on close
    closeAllDropdowns();
  }

  function resetSidebar() {
    if (!sidebar) return;
    sidebar.classList.remove('active', 'expanded', 'collapsed');
    if (overlay) overlay.classList.remove('active');
    document.body.style.overflow = '';
    closeAllDropdowns();
  }

  function closeAllDropdowns() {
    if (!sidebar) return;
    sidebar.querySelectorAll('.nav-item.dropdown-open').forEach(function (item) {
      item.classList.remove('dropdown-open');
    });
  }

  // ========================================
  // ACCORDION DROPDOWNS (mobile only)
  // ========================================
  function initAccordion() {
    if (!sidebar) return;

    sidebar.querySelectorAll('.nav-link.has-dropdown').forEach(function (link) {
      link.addEventListener('click', function (e) {
        if (window.innerWidth > 768) return; // desktop uses hover

        e.preventDefault();
        e.stopPropagation();

        var navItem = link.closest('.nav-item');
        var wasOpen = navItem.classList.contains('dropdown-open');

        // Close all other open dropdowns
        sidebar.querySelectorAll('.nav-item.dropdown-open').forEach(function (item) {
          item.classList.remove('dropdown-open');
        });

        // Toggle current
        if (!wasOpen) {
          navItem.classList.add('dropdown-open');

          // Scroll the open dropdown into view
          setTimeout(function () {
            var dropdown = navItem.querySelector('.dropdown-menu');
            if (dropdown) {
              dropdown.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
          }, 100);
        }
      });
    });
  }

  // ========================================
  // Page actions 3-dots dropdown
  // Shows 1 primary action button outside, moves rest into a "⋯" menu
  // ========================================
  function isBackButton(el) {
    if (!el) return false;
    var btn = el.matches('a.btn, button.btn') ? el : el.querySelector('.btn');
    if (!btn) return false;
    var text = btn.textContent.trim().toLowerCase();
    return text === 'back' || btn.querySelector('.fa-arrow-left') !== null;
  }

  function getButtonElement(item) {
    return item.matches('a.btn, button.btn') ? item : (item.querySelector('.btn') || item);
  }

  function findMainActionButton(items) {
    var list = Array.from(items);
    if (list.length === 0) return null;

    // 1. Explicit data-main-action or data-primary-action marker
    var explicit = list.find(function (el) {
      var btn = getButtonElement(el);
      return el.dataset.mainAction === 'true' ||
        btn.dataset.mainAction === 'true' ||
        el.dataset.primaryAction === 'true' ||
        btn.dataset.primaryAction === 'true' ||
        el.classList.contains('main-action') ||
        btn.classList.contains('main-action');
    });
    if (explicit) return explicit;

    // 2. High priority action: Print (essential in invoices / detail views)
    var printItem = list.find(function (el) {
      var btn = getButtonElement(el);
      return btn.id === 'directPrintBtn' ||
        btn.querySelector('.fa-print') !== null ||
        btn.textContent.toLowerCase().includes('print');
    });
    if (printItem) return printItem;

    // 3. High priority action: Add / Create (e.g. Add Payment, Create Invoice)
    var addItem = list.find(function (el) {
      if (isBackButton(el)) return false;
      var btn = getButtonElement(el);
      var t = btn.textContent.toLowerCase();
      return btn.classList.contains('btn-primary') && (
        btn.querySelector('.fa-plus') !== null ||
        t.includes('add') ||
        t.includes('create') ||
        t.includes('new')
      );
    });
    if (addItem) return addItem;

    // 4. Any .btn-primary or .btn-success (that is not a back button)
    var primaryItem = list.find(function (el) {
      if (isBackButton(el)) return false;
      var btn = getButtonElement(el);
      return btn.classList.contains('btn-primary') || btn.classList.contains('btn-success');
    });
    if (primaryItem) return primaryItem;

    // 5. Any non-back button
    var nonBackItem = list.find(function (el) {
      return !isBackButton(el);
    });
    if (nonBackItem) return nonBackItem;

    // 6. Fallback to first item
    return list[0];
  }

  function initPageActionsDropdowns() {
    document.querySelectorAll('.page-actions:not(.dash-actions-group)').forEach(function (actions) {
      if (actions.dataset.collapsed) return;

      var rawItems = actions.querySelectorAll(':scope > a.btn, :scope > button.btn, :scope > form');
      var items = Array.from(rawItems).filter(function (item) {
        // Exclude date filter forms and filter containers from being treated as action buttons
        if (item.classList && (
          item.classList.contains('date-filter-form') ||
          item.classList.contains('date-filter-container') ||
          item.classList.contains('multipleSelection')
        )) {
          return false;
        }
        if (item.querySelector && item.querySelector('.date-filter-container, .date-filter-select, select, .multipleSelection')) {
          return false;
        }
        if (item.tagName === 'FORM' && !item.querySelector('button.btn, a.btn, input[type="submit"]')) {
          return false;
        }
        return true;
      });

      if (items.length <= 1) return;

      var mainItem = findMainActionButton(items);
      if (!mainItem) return;

      actions.dataset.collapsed = 'true';
      actions.classList.add('has-more');

      var toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'page-actions-toggle';
      toggle.innerHTML = '<i class="fas fa-ellipsis-v"></i>';
      toggle.title = 'More actions';
      toggle.setAttribute('aria-label', 'More actions');

      var dropdown = document.createElement('div');
      dropdown.className = 'page-actions-dropdown';

      // Move all other action items into the dropdown
      items.forEach(function (item) {
        if (item !== mainItem) {
          dropdown.appendChild(item);
        }
      });

      // Keep mainItem visible outside, followed by toggle and dropdown
      if (mainItem.nextSibling) {
        actions.insertBefore(toggle, mainItem.nextSibling);
      } else {
        actions.appendChild(toggle);
      }
      actions.insertBefore(dropdown, toggle.nextSibling);

      toggle.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var wasOpen = dropdown.classList.toggle('open');
        // Close other open dropdowns
        if (wasOpen) {
          document.querySelectorAll('.page-actions-dropdown.open').forEach(function (d) {
            if (d !== dropdown) d.classList.remove('open');
          });
        }
      });
    });
  }

  function destroyPageActionsDropdowns() {
    document.querySelectorAll('.page-actions[data-collapsed]').forEach(function (actions) {
      var dropdown = actions.querySelector('.page-actions-dropdown');
      var toggle = actions.querySelector('.page-actions-toggle');
      if (dropdown) {
        var movedItems = Array.from(dropdown.children);
        movedItems.forEach(function (item) {
          actions.insertBefore(item, toggle || dropdown);
        });
        dropdown.remove();
      }
      if (toggle) toggle.remove();
      actions.classList.remove('has-more');
      delete actions.dataset.collapsed;
    });
  }
  // ========================================
  function initMobileNavClose() {
    if (!sidebar) return;

    sidebar.addEventListener('click', function (e) {
      if (window.innerWidth > 768) return;

      var link = e.target.closest('a');
      if (!link) return;

      // Don't close for dropdown toggles
      if (link.classList.contains('nav-link') && link.classList.contains('has-dropdown')) return;

      // Close for any real link click (even active — let user see navigation)
      if (link.href && link.href !== '#' && !link.href.endsWith('#')) {
        closeSidebar();
      }
    });
  }

  // Initialize on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSidebar);
  } else {
    initSidebar();
  }

})();

// ========================================
// Mobile Row Action Buttons — collapse >2 into three-dots
// ========================================
(function () {
  'use strict';

  function collapseRowActionButtons() {
    var isMobile = window.innerWidth <= 768;
    document.querySelectorAll('td .action-buttons').forEach(function (container) {
      var buttons = container.querySelectorAll(':scope > a.btn-action, :scope > button.btn-action');
      if (buttons.length <= 2) return;

      if (isMobile && !container.dataset.rowCollapsed) {
        container.dataset.rowCollapsed = 'true';
        container.classList.add('has-overflow');

        var toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'row-actions-toggle';
        toggle.innerHTML = '<i class="fas fa-ellipsis-v"></i>';
        toggle.title = 'More actions';

        var dropdown = document.createElement('div');
        dropdown.className = 'row-actions-dropdown';

        for (var i = 2; i < buttons.length; i++) {
          dropdown.appendChild(buttons[i]);
        }

        container.appendChild(dropdown);
        container.appendChild(toggle);

        toggle.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          var wasOpen = dropdown.classList.toggle('open');
          if (wasOpen) {
            document.querySelectorAll('.row-actions-dropdown.open').forEach(function (d) {
              if (d !== dropdown) d.classList.remove('open');
            });
          }
        });
      } else if (!isMobile && container.dataset.rowCollapsed) {
        var dropdown = container.querySelector('.row-actions-dropdown');
        var toggle = container.querySelector('.row-actions-toggle');
        if (dropdown) {
          var movedBtns = dropdown.querySelectorAll('.btn-action');
          movedBtns.forEach(function (btn) {
            container.insertBefore(btn, dropdown);
          });
          dropdown.remove();
        }
        if (toggle) toggle.remove();
        delete container.dataset.rowCollapsed;
        container.classList.remove('has-overflow');
      }
    });
  }

  document.addEventListener('DOMContentLoaded', collapseRowActionButtons);
  document.addEventListener('tableDataLoaded', collapseRowActionButtons);

  // Also run on resize for desktop↔mobile transitions
  var resizeTimer;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(collapseRowActionButtons, 150);
  });

  // Close dropdowns on outside click
  document.addEventListener('click', function (e) {
    if (!e.target.closest('.row-actions-toggle') && !e.target.closest('.row-actions-dropdown')) {
      document.querySelectorAll('.row-actions-dropdown.open').forEach(function (d) {
        d.classList.remove('open');
      });
    }
  });
})();
