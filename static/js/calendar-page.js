/**
 * Interactive Calendar Page Logic
 * Modern, clean, spacious full-width calendar grid with direct day inspection modal.
 */

(function () {
  const ssrEl = document.getElementById('calendar-data');
  if (!ssrEl) return;

  /** @type {Record<string, {amount: number, completed: number, events: Array<{invoice_number: string, customer_name: string, gross_amount: number, discount_amount: number, amount: number, paid_amount: number, status: string, status_display: string, url: string}>}>} */
  let calendarData;
  try {
    calendarData = JSON.parse(ssrEl.textContent);
  } catch (e) {
    console.error('Calendar: failed to parse SSR data', e);
    return;
  }

  const monthKpiEl = document.getElementById('month-kpi');
  let monthKpi = null;
  if (monthKpiEl) {
    try {
      monthKpi = JSON.parse(monthKpiEl.textContent);
    } catch (e) {
      console.error('Calendar: failed to parse month KPI data', e);
    }
  }

  const now = new Date();
  const todayStr = now.getFullYear() + '-'
    + String(now.getMonth() + 1).padStart(2, '0') + '-'
    + String(now.getDate()).padStart(2, '0');

  // Controls
  const monthSelect = document.getElementById('monthSelect');
  const yearSelect = document.getElementById('yearSelect');
  const filterBtns = document.querySelectorAll('.cal-filter-btn');
  const searchInput = document.getElementById('calSearchInput');
  const searchClear = document.getElementById('calSearchClear');

  const params = new URLSearchParams(window.location.search);
  const yearNum = parseInt(params.get('year'), 10) || (yearSelect ? parseInt(yearSelect.value, 10) : 0) || now.getFullYear();
  const month1 = parseInt(params.get('month'), 10) || (monthSelect ? parseInt(monthSelect.value, 10) : 0) || (now.getMonth() + 1);

  // ── DOM References ──
  const grid = document.getElementById('calGrid');
  const pageHeaderAnalyticsBtn = document.getElementById('pageHeaderAnalyticsBtn');

  // Modal elements
  const dateInvoicesModalEl = document.getElementById('dateInvoicesModal');
  const modalLabel = document.getElementById('dateInvoicesModalLabel');
  const modalSubTitle = document.getElementById('modalSubTitle');
  const modalMetricPercentage = document.getElementById('modalMetricPercentage');
  const modalSalesAmount = document.getElementById('modalSalesAmount');
  const modalMetricBar = document.getElementById('modalMetricBar');
  const modalEventsCountBadge = document.getElementById('modalEventsCountBadge');
  const modalEventsList = document.getElementById('modalEventsList');
  const modalAnalyticsLink = document.getElementById('modalAnalyticsLink');

  // KPI elements
  const kpiTotalBilling = document.getElementById('kpiTotalBilling');
  const kpiTotalInvoices = document.getElementById('kpiTotalInvoices');
  const kpiBillCountSubtitle = document.getElementById('kpiBillCountSubtitle');
  const kpiPaidAmount = document.getElementById('kpiPaidAmount');
  const kpiPendingAmount = document.getElementById('kpiPendingAmount');
  const kpiCollectionRatePill = document.getElementById('kpiCollectionRatePill');
  const kpiDailyAvg = document.getElementById('kpiDailyAvg');
  const paidPctText = document.getElementById('paidPctText');
  const paidAmtText = document.getElementById('paidAmtText');
  const pendingPctText = document.getElementById('pendingPctText');
  const pendingAmtText = document.getElementById('pendingAmtText');
  const kpiPaidBar = document.getElementById('kpiPaidBar');
  const kpiPendingBar = document.getElementById('kpiPendingBar');

  // Active State
  let activeFilter = 'ALL';
  let activeSearchQuery = '';
  let selectedKey = null;

  // ── Helpers ──
  const dateKey = (y, m1, d) =>
    y + '-' + String(m1).padStart(2, '0') + '-' + String(d).padStart(2, '0');

  function daysInMonth(y, m1) {
    return new Date(y, m1, 0).getDate();
  }

  function firstDayOfWeek(y, m1) {
    return new Date(y, m1 - 1, 1).getDay();
  }

  function formatNumberSafe(amount) {
    if (typeof formatNumber === 'function') {
      return formatNumber(amount);
    }
    return Number(amount || 0).toLocaleString('en-IN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function formatCompactAmount(amount) {
    const num = Number(amount || 0);
    const hasDecimals = (num % 1 !== 0);
    return num.toLocaleString('en-IN', {
      minimumFractionDigits: hasDecimals ? 2 : 0,
      maximumFractionDigits: 2,
    });
  }

  function statusBadgeClass(status) {
    if (status === 'PAID') return 'bg-success';
    if (status === 'UNPAID') return 'bg-danger';
    if (status === 'PARTIALLY_PAID') return 'bg-warning text-dark';
    return 'bg-secondary';
  }

  function statusBorderClass(status) {
    if (status === 'PAID') return 'event-success';
    if (status === 'UNPAID') return 'event-danger';
    if (status === 'PARTIALLY_PAID') return 'event-warning';
    return '';
  }

  function formatDisplayDate(key) {
    const parts = key.split('-');
    const dateObj = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
    return dateObj.toLocaleDateString('en-IN', {
      weekday: 'short', day: 'numeric', month: 'short', year: 'numeric'
    });
  }

  // ── Month & Year Navigation ──
  if (monthSelect) {
    monthSelect.addEventListener('change', function () {
      navigateTo(yearSelect ? yearSelect.value : yearNum, this.value);
    });
  }

  if (yearSelect) {
    yearSelect.addEventListener('change', function () {
      navigateTo(this.value, monthSelect ? monthSelect.value : month1);
    });
  }

  function navigateTo(year, month) {
    window.location.href = '?year=' + year + '&month=' + month;
  }

  // ── Filter Buttons ──
  filterBtns.forEach(function (btn) {
    btn.addEventListener('click', function () {
      filterBtns.forEach(function (b) { b.classList.remove('active'); });
      this.classList.add('active');
      activeFilter = this.dataset.filter || 'ALL';
      applyFilters();
    });
  });

  // ── Search Input ──
  if (searchInput) {
    searchInput.addEventListener('input', function () {
      activeSearchQuery = this.value.trim().toLowerCase();
      if (searchClear) {
        searchClear.style.display = activeSearchQuery ? 'block' : 'none';
      }
      applyFilters();
    });
  }

  if (searchClear) {
    searchClear.addEventListener('click', function () {
      if (searchInput) searchInput.value = '';
      activeSearchQuery = '';
      this.style.display = 'none';
      applyFilters();
    });
  }

  // ── Calculate Top KPI Bar Metrics ──
  function calculateKpis() {
    let grandGrossBilling = 0;
    let grandTotalInvoices = 0;
    let grandPaidAmount = 0;
    let grandPendingAmount = 0;

    const monthPrefix = dateKey(yearNum, month1, 1).substring(0, 7);

    Object.entries(calendarData).forEach(function ([dateStr, dayData]) {
      if (!dateStr.startsWith(monthPrefix)) return;
      if (!dayData || !dayData.events) return;

      dayData.events.forEach(function (ev) {
        let searchMatch = true;
        if (activeSearchQuery !== '') {
          const invNum = (ev.invoice_number || '').toLowerCase();
          const custName = (ev.customer_name || '').toLowerCase();
          searchMatch = invNum.includes(activeSearchQuery) || custName.includes(activeSearchQuery);
        }
        if (!searchMatch) return;

        let statusMatch = true;
        if (activeFilter === 'PAID') statusMatch = (ev.status === 'PAID');
        if (activeFilter === 'PENDING') statusMatch = (ev.status !== 'PAID');

        if (!statusMatch) return;

        const net = ev.amount || 0;
        const paid = ev.paid_amount !== undefined ? ev.paid_amount : (ev.status === 'PAID' ? net : 0);
        const pending = Math.max(0, net - paid);

        grandGrossBilling += net;
        grandTotalInvoices += 1;
        grandPaidAmount += paid;
        grandPendingAmount += pending;
      });
    });

    // If default view with monthKpi available
    if (activeFilter === 'ALL' && !activeSearchQuery && monthKpi) {
      grandGrossBilling = Math.max(0, monthKpi.total_billing || 0);
      grandTotalInvoices = Math.max(0, monthKpi.total_invoices || 0);
      grandPaidAmount = Math.max(0, monthKpi.paid_amount || 0);
      grandPendingAmount = Math.max(0, monthKpi.pending_amount || 0);
    } else {
      grandGrossBilling = Math.max(0, grandGrossBilling);
      grandTotalInvoices = Math.max(0, grandTotalInvoices);
      grandPaidAmount = Math.max(0, grandPaidAmount);
      grandPendingAmount = Math.max(0, grandPendingAmount);
    }

    if (typeof updateAllCounters === "function") {
      updateAllCounters({
        kpiTotalBilling: grandGrossBilling,
        kpiPaidAmount: grandPaidAmount,
        kpiPendingAmount: grandPendingAmount
      });
    } else {
      if (kpiTotalBilling) kpiTotalBilling.textContent = formatNumberSafe(grandGrossBilling);
      if (kpiPaidAmount) kpiPaidAmount.textContent = formatNumberSafe(grandPaidAmount);
      if (kpiPendingAmount) kpiPendingAmount.textContent = formatNumberSafe(grandPendingAmount);
    }

    if (kpiTotalInvoices) {
      kpiTotalInvoices.textContent = grandTotalInvoices;
    }
    if (kpiBillCountSubtitle) {
      kpiBillCountSubtitle.textContent = grandTotalInvoices;
    }

    // Collection Rate & Progress
    const rate = grandGrossBilling > 0 ? Math.round((grandPaidAmount / grandGrossBilling) * 100) : 0;
    const pendingRate = Math.max(0, 100 - rate);

    if (kpiCollectionRatePill) {
      kpiCollectionRatePill.textContent = rate + '% Collected';
    }
    if (paidPctText) paidPctText.textContent = rate + '%';
    if (paidAmtText) paidAmtText.textContent = formatNumberSafe(grandPaidAmount);
    if (pendingPctText) pendingPctText.textContent = pendingRate + '%';
    if (pendingAmtText) pendingAmtText.textContent = formatNumberSafe(grandPendingAmount);
    if (kpiPaidBar) kpiPaidBar.style.width = rate + '%';
    if (kpiPendingBar) kpiPendingBar.style.width = pendingRate + '%';

    // Daily Average
    const numDays = daysInMonth(yearNum, month1);
    const avgSales = numDays > 0 ? (grandGrossBilling / numDays) : 0;
    if (kpiDailyAvg) {
      kpiDailyAvg.textContent = formatNumberSafe(avgSales);
    }
  }

  // ── Build Full-Width Calendar Grid ──
  function buildGrid() {
    grid.innerHTML = '';
    const fragment = document.createDocumentFragment();
    const totalDays = daysInMonth(yearNum, month1);
    const startDay = firstDayOfWeek(yearNum, month1);
    const prevMonth1 = month1 === 1 ? 12 : month1 - 1;
    const prevYear = month1 === 1 ? yearNum - 1 : yearNum;
    const prevTotal = daysInMonth(prevYear, prevMonth1);

    // Filler from previous month
    for (let i = startDay - 1; i >= 0; i--) {
      const dayNum = prevTotal - i;
      const key = dateKey(prevYear, prevMonth1, dayNum);
      fragment.appendChild(makeCell(dayNum, true, key));
    }

    // Current month days
    for (let d = 1; d <= totalDays; d++) {
      const key = dateKey(yearNum, month1, d);
      fragment.appendChild(makeCell(d, false, key));
    }

    // Filler from next month
    const filled = startDay + totalDays;
    const rem = filled <= 35 ? 35 - filled : 42 - filled;
    const nextMonth1 = month1 === 12 ? 1 : month1 + 1;
    const nextYear = month1 === 12 ? yearNum + 1 : yearNum;
    for (let d = 1; d <= rem; d++) {
      const key = dateKey(nextYear, nextMonth1, d);
      fragment.appendChild(makeCell(d, true, key));
    }

    grid.appendChild(fragment);
    calculateKpis();
  }

  function makeCell(day, isOther, key) {
    const cell = document.createElement('div');
    cell.className = 'cal-cell';
    if (isOther) cell.classList.add('other-month');

    if (key) {
      cell.dataset.date = key;
      const isToday = (key === todayStr);
      if (isToday) cell.classList.add('today');

      const dayData = calendarData[key];
      const hasEvents = dayData && dayData.events && dayData.events.length > 0;

      let topRowHtml = '<div class="cell-top-row"><span class="cell-date">' + day + '</span>';
      if (isToday) {
        topRowHtml += '<span class="today-tag">TODAY</span>';
      } else if (hasEvents) {
        const count = dayData.events.length;
        const totalAmount = dayData.amount || 0;
        const completedAmount = dayData.completed || 0;
        const isPaidFull = completedAmount >= totalAmount && totalAmount > 0;
        const isPaidPartial = completedAmount > 0 && completedAmount < totalAmount;
        const dotClass = isPaidFull ? 'dot-paid' : (isPaidPartial ? 'dot-pending' : 'dot-unpaid');

        topRowHtml += '<span class="cell-meta"><span class="status-dot ' + dotClass + '"></span>' + count + ' ' + (count === 1 ? 'bill' : 'bills') + '</span>';
      }
      topRowHtml += '</div>';

      let bodyHtml = '';
      if (hasEvents) {
        cell.classList.add('has-sales');
        const totalAmount = dayData.amount || 0;
        bodyHtml = '<div class="cal-amount">' + formatCompactAmount(totalAmount) + '</div>';
      }

      cell.innerHTML = topRowHtml + bodyHtml;

      cell.addEventListener('click', function () {
        selectCell(cell, key);
      });
    } else {
      cell.innerHTML = '<span class="cell-date">' + day + '</span>';
    }
    return cell;
  }

  // ── Date Cell Selection & Modal Inspection ──
  function selectCell(cell, key) {
    selectedKey = key;
    grid.querySelectorAll('.cal-cell.selected').forEach(function (c) { c.classList.remove('selected'); });
    cell.classList.add('selected');

    openDateInvoicesModal(key);
  }

  // ── Open Day Invoices Modal ──
  function openDateInvoicesModal(key) {
    const formattedDate = formatDisplayDate(key);

    if (modalLabel) modalLabel.textContent = formattedDate;
    if (modalSubTitle) modalSubTitle.textContent = 'Day Revenue & Invoices List';

    if (modalAnalyticsLink) {
      modalAnalyticsLink.href = '/calendar/details/?start=' + key + '&end=' + key;
    }

    const dayData = calendarData[key];
    const events = (dayData && dayData.events) ? dayData.events : [];
    let dayTotalAmount = dayData ? (dayData.amount || 0) : 0;
    let dayCompleted = dayData ? (dayData.completed || 0) : 0;

    let filtered = events.filter(function (ev) {
      let statusMatch = true;
      if (activeFilter === 'PAID') statusMatch = (ev.status === 'PAID');
      if (activeFilter === 'PENDING') statusMatch = (ev.status !== 'PAID');
      let searchMatch = true;
      if (activeSearchQuery !== '') {
        searchMatch = (ev.invoice_number || '').toLowerCase().includes(activeSearchQuery) ||
                      (ev.customer_name || '').toLowerCase().includes(activeSearchQuery);
      }
      return statusMatch && searchMatch;
    });

    if (modalSalesAmount) {
      modalSalesAmount.textContent = formatNumberSafe(dayCompleted) + ' / ' + formatNumberSafe(dayTotalAmount);
    }
    const pct = dayTotalAmount > 0 ? (dayCompleted / dayTotalAmount) * 100 : 0;
    if (modalMetricBar) modalMetricBar.style.width = pct.toFixed(1) + '%';
    if (modalMetricPercentage) modalMetricPercentage.textContent = Math.round(pct) + '% Paid';
    if (modalEventsCountBadge) modalEventsCountBadge.textContent = filtered.length;

    renderModalEvents(filtered);

    if (dateInvoicesModalEl && typeof bootstrap !== 'undefined') {
      const bsModal = bootstrap.Modal.getOrCreateInstance(dateInvoicesModalEl);
      bsModal.show();
    }
  }

  function renderModalEvents(events) {
    if (!modalEventsList) return;

    if (!events.length) {
      modalEventsList.innerHTML =
        '<div class="events-placeholder p-4 text-center text-muted">' +
          '<i class="fa-solid fa-folder-open fs-3 mb-2 opacity-50"></i>' +
          '<p class="small mb-0">No invoices recorded for this date or matching current filter.</p>' +
        '</div>';
      return;
    }

    let html = '';
    events.forEach(function (ev) {
      const borderCls = statusBorderClass(ev.status);
      const badgeCls = statusBadgeClass(ev.status);

      html +=
        '<a href="' + (ev.url || '#') + '" class="cal-modal-event-item ' + borderCls + '">' +
          '<div class="d-flex justify-content-between align-items-center mb-1">' +
            '<span class="cal-modal-event-inv"><i class="fa-solid fa-file-invoice me-1 text-primary"></i>' + escapeHtml(ev.invoice_number) + '</span>' +
            '<span class="badge ' + badgeCls + ' px-2 py-1" style="font-size: 0.68rem;">' + escapeHtml(ev.status_display || ev.status) + '</span>' +
          '</div>' +
          '<div class="d-flex justify-content-between align-items-center mt-1">' +
            '<span class="cal-modal-event-cust"><i class="fa-solid fa-user me-1"></i>' + escapeHtml(ev.customer_name) + '</span>' +
            '<span class="cal-modal-event-amt">' + formatNumberSafe(ev.amount) + '</span>' +
          '</div>' +
        '</a>';
    });

    modalEventsList.innerHTML = html;
  }

  // ── Apply Filters (Status & Search) ──
  function applyFilters() {
    const cells = grid.querySelectorAll('.cal-cell[data-date]');
    cells.forEach(function (cell) {
      const key = cell.dataset.date;
      const dayData = calendarData[key];

      if (!dayData || !dayData.events.length) {
        if (activeFilter !== 'ALL' || activeSearchQuery !== '') {
          cell.classList.add('filtered-out');
        } else {
          cell.classList.remove('filtered-out');
        }
        return;
      }

      let matches = dayData.events.filter(function (ev) {
        let statusMatch = true;
        if (activeFilter === 'PAID') statusMatch = (ev.status === 'PAID');
        if (activeFilter === 'PENDING') statusMatch = (ev.status !== 'PAID');

        let searchMatch = true;
        if (activeSearchQuery !== '') {
          const invNum = (ev.invoice_number || '').toLowerCase();
          const custName = (ev.customer_name || '').toLowerCase();
          searchMatch = invNum.includes(activeSearchQuery) || custName.includes(activeSearchQuery);
        }

        return statusMatch && searchMatch;
      });

      if (matches.length > 0) {
        cell.classList.remove('filtered-out');
      } else {
        cell.classList.add('filtered-out');
      }
    });

    calculateKpis();

    if (selectedKey && dateInvoicesModalEl && dateInvoicesModalEl.classList.contains('show')) {
      openDateInvoicesModal(selectedKey);
    }
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }

  // ── Boot ──
  if (pageHeaderAnalyticsBtn) {
    const startStr = dateKey(yearNum, month1, 1);
    const endStr = dateKey(yearNum, month1, daysInMonth(yearNum, month1));
    pageHeaderAnalyticsBtn.href = '/calendar/details/?start=' + startStr + '&end=' + endStr;
  }

  buildGrid();

})();
