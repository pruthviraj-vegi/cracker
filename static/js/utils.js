/**
 * Global Frontend Utilities for My_Billing application.
 * Contains shared helpers: debounce, formatCurrency, formatNumber, formatIndianNumber,
 * escapeHtml, escapeAttr, onClickOutside, date utilities, counter animations, and date filter helpers.
 */

/**
 * Standardized debounce function.
 * Delays invoking func until after wait milliseconds have elapsed since the last time it was invoked.
 */
function debounce(func, wait = 300) {
  let timeout;
  return function executedFunction(...args) {
    const context = this;
    const later = () => {
      timeout = null;
      func.apply(context, args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

/**
 * Standardized throttle function.
 */
function throttle(func, limit = 200) {
  let inThrottle;
  return function executedFunction(...args) {
    const context = this;
    if (!inThrottle) {
      func.apply(context, args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
}

/**
 * Formats a numeric value into a formatted number string (Indian locale standard).
 * Per project rules, no currency symbol (₹) is generated.
 */
function formatCurrency(amount, locale = 'en-IN') {
  const numericAmount = parseFloat(amount) || 0;
  return new Intl.NumberFormat(locale, {
    style: 'decimal',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numericAmount);
}

/**
 * Formats a numeric value into a decimal string without currency symbol.
 */
function formatNumber(amount, locale = 'en-IN', decimals = 2) {
  const numericAmount = parseFloat(amount) || 0;
  return new Intl.NumberFormat(locale, {
    style: 'decimal',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(numericAmount);
}

/**
 * Formats input or numeric string using Indian number formatting rules.
 */
function formatIndianNumber(value, maxDecimals = 2) {
  if (value === undefined || value === null) {
    return '';
  }
  value = String(value);

  let isNegative = value.indexOf('-') === 0;
  value = value.replace(/[^\d.]/g, '');

  const decimalCount = (value.match(/\./g) || []).length;
  if (decimalCount > 1) {
    const firstDecimalIndex = value.indexOf('.');
    value = value.slice(0, firstDecimalIndex + 1) +
            value.slice(firstDecimalIndex + 1).replace(/\./g, '');
  }

  let [intPart, decPart] = value.split('.');

  if (intPart && intPart.length > 0) {
    intPart = intPart.replace(/^0+/, '');
    if (!intPart) {
      intPart = '0';
    }

    if (intPart.length > 3) {
      let last3 = intPart.slice(-3);
      let others = intPart.slice(0, -3);
      intPart = others.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + last3;
    }
  }

  let result = intPart;

  if (decPart !== undefined) {
    decPart = decPart.slice(0, maxDecimals);
    result = intPart + '.' + decPart;
  } else if (value.endsWith('.')) {
    result = intPart + '.';
  }

  if (isNegative && result && result !== '0') {
    return '-' + result;
  } else if (isNegative) {
    return '-';
  }

  return result || '';
}

/**
 * Sanitizes and escapes HTML characters to prevent XSS.
 */
function escapeHtml(str) {
  if (typeof str !== 'string') return str || '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

/**
 * Sanitizes and escapes HTML attributes.
 */
function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, '&quot;');
}

/**
 * Listens for click events outside the target element and triggers a callback.
 */
function onClickOutside(element, callback) {
  if (!element || typeof callback !== 'function') return () => {};

  const listener = (event) => {
    if (!element.contains(event.target)) {
      callback(event);
    }
  };

  document.addEventListener('click', listener);
  document.addEventListener('touchstart', listener);

  return () => {
    document.removeEventListener('click', listener);
    document.removeEventListener('touchstart', listener);
  };
}

/**
 * Date calculation helpers
 */
function daysInMonth(year, month) {
  return new Date(year, month + 1, 0).getDate();
}

function firstDayOfWeek(year, month) {
  return new Date(year, month, 1).getDay();
}

function dateKey(date) {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/**
 * Formats date into Indian locale format (e.g. "27 Jul 2026").
 */
function formatDate(date) {
  if (!date) return '';
  return new Intl.DateTimeFormat('en-IN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  }).format(new Date(date));
}

/**
 * Copy text to clipboard with fallback and toast notification.
 */
function copyToClipboard(text) {
  function fallbackCopy(t) {
    const textarea = document.createElement('textarea');
    textarea.value = t;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    if (typeof showNotification === 'function') {
      showNotification('Copied to clipboard!', 'success');
    }
  }

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        if (typeof showNotification === 'function') {
          showNotification('Copied to clipboard!', 'success');
        }
      })
      .catch(() => fallbackCopy(text));
  } else {
    fallbackCopy(text);
  }
}

// Global safe fallback for showNotification to prevent ReferenceErrors
if (typeof window.showNotification !== 'function') {
  window._pendingNotifications = window._pendingNotifications || [];
  window.showNotification = function (message, type = 'info', duration = 3500) {
    window._pendingNotifications.push({ message, type, duration });
  };
}

/* ============================================================================
 * ANIMATED COUNTER UTILITIES
 * ============================================================================ */
function animateCounter(element, startValue, endValue, duration = 800) {
  const safeStart = Number(startValue) || 0;
  const safeEnd = Number(endValue) || 0;
  const startTime = performance.now();
  const difference = safeEnd - safeStart;
  const prefix = element.getAttribute("data-prefix") || "";
  const suffix = element.getAttribute("data-suffix") || "";
  const forceDecimals = element.getAttribute("data-decimals");

  const localeOptsWithDecimals = { maximumFractionDigits: 2, minimumFractionDigits: 2 };
  const localeOptsNoDecimals = { maximumFractionDigits: 0, minimumFractionDigits: 0 };

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const easeOutQuad = 1 - (1 - progress) * (1 - progress);

    let currentValue = safeStart + difference * easeOutQuad;
    if (Math.abs(currentValue) < 0.001) {
      currentValue = 0;
    }

    const hasDecimal = forceDecimals !== null ? forceDecimals === "2" : (currentValue % 1 !== 0 || safeEnd % 1 !== 0);
    const formattedValue = currentValue.toLocaleString("en-IN",
      hasDecimal ? localeOptsWithDecimals : localeOptsNoDecimals
    );

    element.textContent = prefix + formattedValue + suffix;
    element.setAttribute("data-count", currentValue.toFixed(2));

    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      const finalHasDecimal = forceDecimals !== null ? forceDecimals === "2" : (safeEnd % 1 !== 0);
      element.textContent = prefix + safeEnd.toLocaleString("en-IN",
        finalHasDecimal ? localeOptsWithDecimals : localeOptsNoDecimals
      ) + suffix;
      element.setAttribute("data-count", safeEnd.toFixed(2));
    }
  }

  requestAnimationFrame(update);
}

function initializeCounters() {
  const countingElements = document.getElementsByClassName("counting-number");
  for (const element of countingElements) {
    const rawDataCount = element.getAttribute("data-count");
    const initialValue = rawDataCount !== null && !isNaN(parseFloat(rawDataCount))
      ? parseFloat(rawDataCount)
      : (parseFloat(element.textContent.replace(/[^0-9.-]+/g, "")) || 0);
    element.setAttribute("data-count", initialValue.toFixed(2));
    animateCounter(element, 0, initialValue);
  }
}

function updateCount(elementId, newValue) {
  const element = document.getElementById(elementId);
  if (!element) {
    return;
  }

  const numericValue = typeof newValue === "string"
    ? (parseFloat(newValue.replace(/[^0-9.-]+/g, "")) || 0)
    : (Number(newValue) || 0);

  if (isNaN(numericValue)) {
    return;
  }

  const rawDataCount = element.getAttribute("data-count");
  const currentValue = rawDataCount !== null && !isNaN(parseFloat(rawDataCount))
    ? parseFloat(rawDataCount)
    : (parseFloat(element.textContent.replace(/[^0-9.-]+/g, "")) || 0);

  animateCounter(element, currentValue, numericValue);
}

function updateAllCounters(valuesObject) {
  for (const [elementId, newValue] of Object.entries(valuesObject)) {
    updateCount(elementId, newValue);
  }
}

/* ============================================================================
 * DATE FILTER & API UTILITIES
 * ============================================================================ */
function getDateFilterData(filterId = 'dateFilter') {
    const styledRef = window[filterId + '_styled'] || window.dateFilter_styled || window.reportDateFilter_styled;
    const hiddenSelect = styledRef?.hiddenSelect ||
        document.getElementById(filterId) ||
        document.getElementById(filterId + '_hidden') ||
        document.getElementById('reportDateFilter') ||
        document.getElementById('dateFilter');

    if (!hiddenSelect) {
        return {
            isValid: false,
            error: 'Date filter not found. Please refresh the page.',
            data: null
        };
    }

    const selectedValue = hiddenSelect.value;
    const requestData = { date_filter: selectedValue };

    if (selectedValue === 'custom') {
        const customFromDate = document.getElementById(filterId + '_fromDate') || document.getElementById('customFromDate') || document.getElementById('standaloneFrom');
        const customToDate = document.getElementById(filterId + '_toDate') || document.getElementById('customToDate') || document.getElementById('standaloneTo');

        let fromDate = null;
        let toDate = null;

        if (hiddenSelect && hiddenSelect.hasAttribute('data-from-date')) {
            fromDate = hiddenSelect.getAttribute('data-from-date');
            toDate = hiddenSelect.getAttribute('data-to-date');
        }

        if (!fromDate || !toDate) {
            if (styledRef?.fromDateInput && styledRef?.toDateInput) {
                fromDate = styledRef.fromDateInput.getAttribute('data-iso-date') || styledRef.fromDateInput.value;
                toDate = styledRef.toDateInput.getAttribute('data-iso-date') || styledRef.toDateInput.value;
            } else if (customFromDate && customToDate) {
                fromDate = customFromDate.getAttribute('data-iso-date') || customFromDate.value;
                toDate = customToDate.getAttribute('data-iso-date') || customToDate.value;
            }
        }

        if (!fromDate || !toDate) {
            return {
                isValid: false,
                error: 'Please select both From and To dates for custom date range.',
                data: null
            };
        }

        if (new Date(fromDate) > new Date(toDate)) {
            return {
                isValid: false,
                error: 'From date must be before or equal to To date.',
                data: null
            };
        }

        requestData.from_date = fromDate;
        requestData.to_date = toDate;
    }

    return {
        isValid: true,
        error: null,
        data: requestData
    };
}

function getDateFilterValue(filterId = 'dateFilter') {
    const res = getDateFilterData(filterId);
    if (res && res.isValid && res.data) {
        return res.data;
    }
    return 'today';
}

window.getDateFilterValue = getDateFilterValue;

function initDateFilter(selectId = 'dateFilter', options = {}) {
    const selectEl = document.getElementById(selectId);
    if (!selectEl) return null;

    const datasetShowCustom = selectEl.getAttribute('data-show-custom');
    const showCustom = options.showCustomDates !== undefined
        ? options.showCustomDates
        : (datasetShowCustom !== null ? datasetShowCustom === 'true' : true);

    if (typeof convertSelectToStyledDropdown !== 'undefined') {
        const instance = convertSelectToStyledDropdown(selectId, {
            showCustomDates: showCustom,
            onChange: function(data) {
                if (typeof options.onChange === 'function') {
                    options.onChange(data);
                }
            },
            onError: function(err) {
                if (typeof options.onError === 'function') {
                    options.onError(err);
                } else {
                    console.error('Date filter error:', err);
                }
            }
        });
        window[selectId + '_styled'] = instance;
        return instance;
    } else {
        selectEl.addEventListener('change', function(e) {
            if (typeof options.onChange === 'function') {
                options.onChange({
                    value: e.target.value,
                    text: e.target.options[e.target.selectedIndex]?.text || e.target.value
                });
            }
        });
        return null;
    }
}

function setButtonLoading(button, isLoading, loadingText = 'Loading...') {
    if (!button) {
        console.error('Button element not provided to setButtonLoading');
        return;
    }

    if (!button.hasAttribute('data-original-text')) {
        button.setAttribute('data-original-text', button.innerHTML);
        button.setAttribute('data-original-disabled', button.disabled);
    }

    if (isLoading) {
        button.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${loadingText}`;
        button.disabled = true;
        button.classList.add('disabled');
    } else {
        const originalText = button.getAttribute('data-original-text');
        const originalDisabled = button.getAttribute('data-original-disabled') === 'true';

        button.innerHTML = originalText;
        button.disabled = originalDisabled;
        button.classList.remove('disabled');

        button.removeAttribute('data-original-text');
        button.removeAttribute('data-original-disabled');
    }
}

function buildDateFilterUrl(baseUrl, filterData) {
    if (!baseUrl || !filterData) {
        console.error('Invalid parameters for buildDateFilterUrl');
        return baseUrl;
    }

    const separator = baseUrl.includes('?') ? '&' : '?';
    let url = `${baseUrl}${separator}date_filter=${encodeURIComponent(filterData.date_filter)}`;

    if (filterData.from_date) {
        url += `&from_date=${encodeURIComponent(filterData.from_date)}`;
    }

    if (filterData.to_date) {
        url += `&to_date=${encodeURIComponent(filterData.to_date)}`;
    }

    return url;
}

async function handleFetchResponse(response) {
    if (!response.ok) {
        try {
            const data = await response.json();
            throw new Error(data.error || data.message || `Server error: ${response.status}`);
        } catch (jsonError) {
            throw new Error(`Server error: ${response.status} ${response.statusText}`);
        }
    }
    return await response.json();
}

function getCsrfToken() {
    // 1. Global variable set in base.html
    if (typeof window !== 'undefined' && window.csrfToken) {
        return window.csrfToken;
    }

    // 2. Meta tag
    const metaTag = document.querySelector('meta[name="csrf-token"]');
    if (metaTag && metaTag.content) {
        return metaTag.content;
    }

    // 3. Hidden form input
    const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
    if (csrfInput && csrfInput.value) {
        return csrfInput.value;
    }

    // 4. Fallback to cookies if readable (e.g. non-HttpOnly environments)
    if (typeof document !== 'undefined' && document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.startsWith('billing_csrftoken=')) {
                return decodeURIComponent(cookie.substring('billing_csrftoken='.length));
            }
            if (cookie.startsWith('csrftoken=')) {
                return decodeURIComponent(cookie.substring('csrftoken='.length));
            }
        }
    }

    return null;
}

function showErrorAlert(action, error) {
    console.error(`Error ${action}:`, error);

    let errorMessage = `❌ Failed to ${action}.\n\n`;

    if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
        errorMessage += 'Network error: Please check your internet connection and try again.';
    } else if (error.message.includes('403')) {
        errorMessage += 'Permission denied: You may not have access to this feature.';
    } else if (error.message.includes('404')) {
        errorMessage += 'Service not found: Please contact support.';
    } else if (error.message.includes('500')) {
        errorMessage += 'Server error: Please try again later or contact support.';
    } else {
        errorMessage += error.message || 'An unexpected error occurred.';
    }

    alert(errorMessage);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    debounce,
    throttle,
    formatCurrency,
    formatNumber,
    formatIndianNumber,
    formatDate,
    escapeHtml,
    escapeAttr,
    onClickOutside,
    copyToClipboard,
    daysInMonth,
    firstDayOfWeek,
    dateKey,
    animateCounter,
    initializeCounters,
    updateCount,
    updateAllCounters,
    getDateFilterData,
    getDateFilterValue,
    initDateFilter,
    setButtonLoading,
    buildDateFilterUrl,
    handleFetchResponse,
    getCsrfToken,
    showErrorAlert,
  };
}
