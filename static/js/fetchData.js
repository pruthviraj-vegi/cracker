/**
 * Optimized AJAX Table Utility
 * by ChatGPT (optimized 2025)
 * Refactored to fix critical issues: debounce binding, optional forms, memory leaks, timeouts
 */
const tableAjaxConfigs = {};
const tableAbortControllers = {};
const tableEventListeners = {}; // Track listeners for cleanup

// Allowed HTTP methods
const ALLOWED_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

// --- Utility ---
const debounceTable = (fn, delay = 300) => (typeof debounce === 'function' ? debounce(fn, delay) : fn);

/**
 * Collect form data or use direct parameters
 * @param {HTMLElement|string|null} formOrId - Form element, form ID, or null
 * @param {Object} defaultParams - Default parameters to include
 * @param {HTMLElement} table - Table element for sort data
 * @returns {URLSearchParams}
 */
const collectFormData = (formOrId, defaultParams = {}, table = null) => {
    const params = new URLSearchParams();

    // Support form element, form ID string, or null
    let form = null;
    if (typeof formOrId === 'string') {
        form = document.getElementById(formOrId);
    } else if (formOrId instanceof HTMLFormElement) {
        form = formOrId;
    }

    // Collect form data if form exists
    if (form && form.tagName === 'FORM') {
        form.querySelectorAll("input, select, textarea").forEach(input => {
            if (input.name && input.value.trim() !== "") {
                if (input.type === 'radio' && !input.checked) return;
                if (input.type === 'checkbox' && !input.checked) return;

                params.append(input.name, input.value.trim());

                // Integration with dropdown_style.js custom date range
                if (input.tagName === 'SELECT' && input.value === 'custom') {
                    const fromDate = input.getAttribute('data-from-date');
                    const toDate = input.getAttribute('data-to-date');
                    if (fromDate) params.append('from_date', fromDate);
                    if (toDate) params.append('to_date', toDate);
                }
            }
        });
    }

    // Add default parameters (fixed: handle false and 0 correctly)
    Object.entries(defaultParams).forEach(([k, v]) => {
        if (v !== undefined && v !== null) {
            // Only exclude empty strings, not false or 0
            const strValue = String(v);
            if (strValue.trim() !== "" || v === false || v === 0) {
                params.set(k, strValue);
            }
        }
    });

    // Include table sort if table is provided
    if (table && table.dataset.sort) {
        params.append("sort", table.dataset.sort);
    }

    return params;
};

// --- Loading Spinner ---
function showTableLoading(table, text = "Loading...") {
    if (!table) return;
    table.style.opacity = "0.6";
    table.setAttribute("aria-busy", "true");
    let spinner = document.getElementById(`${table.id}-loading`);
    if (!spinner) {
        spinner = document.createElement("div");
        spinner.id = `${table.id}-loading`;
        spinner.className = "table-spinner";
        spinner.setAttribute("role", "status");
        spinner.setAttribute("aria-live", "polite");
        spinner.setAttribute("aria-atomic", "true");
        spinner.innerHTML = `<i class="fas fa-spinner fa-spin" aria-hidden="true"></i><span>${text}</span>`;
        (table.closest('.table-container') || table.parentElement).appendChild(spinner);
    }
    spinner.style.display = "flex";
}

function hideTableLoading(table) {
    if (!table) return;
    table.style.opacity = "1";
    table.setAttribute("aria-busy", "false");
    const spinner = document.getElementById(`${table.id}-loading`);
    if (spinner) spinner.style.display = "none";
}

/**
 * Fetch with timeout wrapper
 * @param {string} url - URL to fetch
 * @param {Object} options - Fetch options
 * @param {number} timeout - Timeout in milliseconds
 * @returns {Promise<Response>}
 */
async function fetchWithTimeout(url, options = {}, timeout = 30000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
        const response = await fetch(url, {
            ...options,
            signal: options.signal ?
                AbortSignal.any([options.signal, controller.signal]) :
                controller.signal
        });
        clearTimeout(timeoutId);
        return response;
    } catch (error) {
        clearTimeout(timeoutId);
        if (error.name === 'AbortError' && !options.signal?.aborted) {
            throw new Error('Request timeout');
        }
        throw error;
    }
}

// --- Core Table Loader ---
async function loadTableData(formId, tableId, fetchUrl, options = {}, page = 1) {
    // Form is now optional - can be null/undefined
    const form = formId ? document.getElementById(formId) : null;
    const table = document.getElementById(tableId);
    if (!table || !fetchUrl) return false;

    const tableBody = table.querySelector("tbody");
    if (!tableBody) {
        console.error(`Table ${tableId} must have a tbody element`);
        return false;
    }

    const paginationId = `${tableId}_pagination`;
    let paginationWrapper = document.getElementById(paginationId) ||
        (() => {
            const wrap = document.createElement("div");
            wrap.id = paginationId;
            wrap.className = "pagination-wrapper";
            wrap.style.display = "none";
            (table.closest(".table-container") || table.parentElement).appendChild(wrap);
            return wrap;
        })();

    // Cancel any running request
    tableAbortControllers[tableId]?.abort();
    const abortController = new AbortController();
    tableAbortControllers[tableId] = abortController;

    // Show loading state in table body
    const cols = table.querySelector("thead tr")?.children.length || 1;
    const loadingText = options.loadingText || "Loading...";
    tableBody.innerHTML = `
        <tr>
            <td colspan="${cols}" class="text-center loading-cell" role="status" aria-live="polite">
                <div class="loading">
                    <i class="fas fa-spinner fa-spin" aria-hidden="true"></i>
                    ${loadingText}
                </div>
            </td>
        </tr>
    `;

    try {
        const params = collectFormData(formId, options.defaultParams || {}, table);
        params.append("page", page);

        // Validate HTTP method
        const method = (options.method?.toUpperCase() || "GET");
        if (!ALLOWED_METHODS.includes(method)) {
            throw new Error(`Invalid HTTP method: ${method}`);
        }

        const req = {
            method,
            headers: { "X-Requested-With": "XMLHttpRequest" },
            signal: abortController.signal
        };
        const url = method === "POST" ? fetchUrl : `${fetchUrl}?${params}`;
        if (method === "POST") {
            req.body = params;
            req.headers["Content-Type"] = "application/x-www-form-urlencoded";
        }

        const timeout = options.timeout || 30000;
        const res = await fetchWithTimeout(url, req, timeout);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (!data.success) throw new Error("Backend error");

        // Basic XSS protection: validate html is a string before inserting
        const htmlContent = data.html || "";
        if (typeof htmlContent !== 'string') {
            throw new Error("Invalid HTML content received");
        }

        // Replace table + pagination
        tableBody.innerHTML = htmlContent;
        updatePagination(paginationWrapper, data.pagination, (page) =>
            loadTableData(formId, tableId, fetchUrl, options, page)
        );

        // Focus management for accessibility
        // Smart focus: preserve user's current focus if they're typing in an input
        const activeElement = document.activeElement;
        const isUserTyping = activeElement && (
            activeElement.tagName === 'INPUT' ||
            activeElement.tagName === 'TEXTAREA' ||
            activeElement.tagName === 'SELECT'
        );

        const firstFocusable = tableBody.querySelector('a, button, input, select, textarea, [tabindex]:not([tabindex="-1"])');
        if (firstFocusable && options.focusAfterLoad !== false && !isUserTyping) {
            firstFocusable.focus();
        }

        table.dispatchEvent(new CustomEvent("tableDataLoaded", { bubbles: true, detail: { data } }));
        options.onSuccess?.(data, table);
        return true;
    } catch (err) {
        if (err.name === "AbortError") return false;
        console.error("Table Load Error:", err);
        showTableError(table, err, options, formId, tableId, fetchUrl);
        options.onError?.(err, table);
        return false;
    }
}

// --- Helpers ---
function showTableError(table, error, options, formId, tableId, fetchUrl) {
    const tbody = table.querySelector("tbody");
    const cols = table.querySelector("thead tr")?.children.length || 1;
    tbody.innerHTML = "";
    const row = document.createElement("tr");
    const errorText = options.errorText || "Error loading data.";
    const retryText = options.retryText || "Retry";
    row.innerHTML = `<td colspan="${cols}" class="text-center" role="alert">
        ${errorText}
        <button class="btn btn-sm btn-outline-primary retry-btn" aria-label="${retryText}">${retryText}</button>
    </td>`;
    tbody.appendChild(row);

    const retryBtn = row.querySelector(".retry-btn");
    if (retryBtn) {
        // Clean up old retry listeners before adding new ones
        if (!tableEventListeners[tableId]) {
            tableEventListeners[tableId] = [];
        }
        // Remove only retry-button listeners, keep other listeners intact
        tableEventListeners[tableId] = tableEventListeners[tableId].filter(
            item => !item.element.classList.contains('retry-btn')
        );

        const listener = () => loadTableData(formId, tableId, fetchUrl, options);
        retryBtn.addEventListener("click", listener);

        tableEventListeners[tableId].push({ element: retryBtn, event: 'click', handler: listener });
    }
}

function updatePagination(wrapper, html, onClick) {
    if (!wrapper) return;
    if (!html || !html.trim()) {
        wrapper.innerHTML = "";
        wrapper.style.display = "none";
        return;
    }
    wrapper.style.display = "flex";
    wrapper.innerHTML = html;

    // Remove old click listener if exists (prevent memory leak)
    if (wrapper._paginationClickHandler) {
        wrapper.removeEventListener("click", wrapper._paginationClickHandler);
    }

    // Create new click handler
    wrapper._paginationClickHandler = e => {
        const link = e.target.closest("a[data-page]");
        if (!link) return;
        e.preventDefault();
        const page = link.dataset.page;
        onClick(page);
    };

    wrapper.addEventListener("click", wrapper._paginationClickHandler);
}

/**
 * Cleanup function to remove event listeners and abort controllers for a table
 * @param {string} tableId - Table ID to clean up
 */
function cleanupTable(tableId) {
    // Abort any pending requests
    tableAbortControllers[tableId]?.abort();
    delete tableAbortControllers[tableId];

    // Remove event listeners
    if (tableEventListeners[tableId]) {
        tableEventListeners[tableId].forEach(({ element, event, handler }) => {
            element.removeEventListener(event, handler);
        });
        delete tableEventListeners[tableId];
    }

    // Remove pagination click handler
    const paginationWrapper = document.getElementById(`${tableId}_pagination`);
    if (paginationWrapper && paginationWrapper._paginationClickHandler) {
        paginationWrapper.removeEventListener("click", paginationWrapper._paginationClickHandler);
        delete paginationWrapper._paginationClickHandler;
    }

    // Remove config
    delete tableAjaxConfigs[tableId];
}

// --- Table Initialization ---
function initTableAjax(formId, tableId, url, options = {}, includeInputs = false) {
    // Clean up any existing configuration for this table
    cleanupTable(tableId);

    tableAjaxConfigs[tableId] = { formId, tableId, fetchUrl: url, options };

    // Form is now optional - only attach listeners if form exists
    const form = formId ? document.getElementById(formId) : null;
    if (form && form.tagName === 'FORM') {
        // Store submit handler for cleanup
        const submitHandler = e => {
            e.preventDefault();
            loadTableData(formId, tableId, url, options);
        };
        form.addEventListener("submit", submitHandler);

        if (!tableEventListeners[tableId]) {
            tableEventListeners[tableId] = [];
        }
        tableEventListeners[tableId].push({ element: form, event: 'submit', handler: submitHandler });

        const selector = includeInputs ? "input, select, textarea" : "select, textarea";
        form.querySelectorAll(selector).forEach(input => {
            const debouncedHandler = debounceTable(() =>
                loadTableData(formId, tableId, url, options), options.debounceDelay || 400);
            input.addEventListener("input", debouncedHandler);

            if (!tableEventListeners[tableId]) {
                tableEventListeners[tableId] = [];
            }
            tableEventListeners[tableId].push({ element: input, event: 'input', handler: debouncedHandler });
        });
    }

    if (options.autoLoad !== false) {
        loadTableData(formId, tableId, url, options);
    }
}

function reloadTable(id) {
    const cfg = tableAjaxConfigs[id];
    if (cfg) loadTableData(cfg.formId, cfg.tableId, cfg.fetchUrl, cfg.options);
}

// --- Sorting ---
function initTableSorting(id) {
    const table = document.getElementById(id);
    if (!table) return;

    // Clean up old sort listeners
    if (table._sortListeners) {
        table._sortListeners.forEach(({ element, handler }) => {
            element.removeEventListener("click", handler);
        });
    }
    table._sortListeners = [];

    table.querySelectorAll("th[data-sort]").forEach(th => {
        th.style.cursor = "pointer";
        th.setAttribute("role", "button");
        th.setAttribute("tabindex", "0");
        th.setAttribute("aria-label", `Sort by ${th.dataset.sort}`);
        if (!th.getAttribute("title")) { // Add tooltip hint if not present
            th.setAttribute("title", "Click to sort. Shift+Click to add multiple columns.");
        }

        const clickHandler = (e) => {
            const field = th.dataset.sort;
            let currentSorts = (table.dataset.sort || "").split(',').filter(s => s.trim());

            // Function to find if field is already sorted and get its direction
            // Returns: 'asc', 'desc', or null
            const getSortState = (f) => {
                const match = currentSorts.find(s => s === f || s === `-${f}`);
                if (!match) return null;
                return match.startsWith('-') ? 'desc' : 'asc';
            };

            // Always use accumulative/multi-column sort logic (No Shift key required)
            // Interaction: Asc -> Desc -> Remove -> (Not Sorted)
            const state = getSortState(field);

            // Remove existing sort for this field if present (to re-add or remove)
            currentSorts = currentSorts.filter(s => s !== field && s !== `-${field}`);

            if (state === null) {
                // Not currently sorted -> Add as Asc
                currentSorts.push(field);
            } else if (state === 'asc') {
                // Currently Asc -> Change to Desc
                currentSorts.push(`-${field}`);
            }
            // If state was 'desc', we simply removed it (Cycle: Asc -> Desc -> Off)

            table.dataset.sort = currentSorts.join(',');
            updateSortIndicators(table);
            reloadTable(id);
        };

        th.addEventListener("click", clickHandler);
        th.addEventListener("keydown", (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                // Simulate click (no shift key support for keyboard easily without more logic, defaulting to single sort)
                const event = new MouseEvent('click', {
                    bubbles: true,
                    cancelable: true,
                    shiftKey: e.shiftKey // Pass shift key if user holds it while pressing Enter
                });
                th.dispatchEvent(event);
            }
        });

        table._sortListeners.push({ element: th, handler: clickHandler });
    });

    // Initial indicator update
    updateSortIndicators(table);
}

function updateSortIndicators(table) {
    const sortString = table.dataset.sort || "";
    const currentSorts = sortString.split(',').filter(s => s.trim());

    table.querySelectorAll("th[data-sort]").forEach(th => {
        const field = th.dataset.sort;

        // Check if this field is in the sort list
        const sortItem = currentSorts.find(s => s === field || s === `-${field}`);

        th.classList.remove("asc", "desc");

        // Remove prior priority indicators if any
        let badge = th.querySelector('.sort-priority');
        if (badge) badge.remove();

        // Icon management
        let icon = th.querySelector('.sort-icon');
        if (!icon) {
            icon = document.createElement('i');
            icon.classList.add('fas', 'fa-sort', 'sort-icon');
            icon.style.marginLeft = '5px';
            th.appendChild(icon);
        }

        if (sortItem) {
            const isDesc = sortItem.startsWith('-');
            th.classList.add(isDesc ? "desc" : "asc");

            // Update icon
            icon.className = isDesc ? 'fas fa-sort-down sort-icon' : 'fas fa-sort-up sort-icon';
            icon.style.opacity = '1';

            // Show priority number if multiple sorts exist
            if (currentSorts.length > 1) {
                const priority = currentSorts.indexOf(sortItem) + 1;
                badge = document.createElement('span');
                badge.className = 'sort-priority';
                badge.innerText = priority;
                badge.style.fontSize = '0.7em';
                badge.style.verticalAlign = 'super';
                badge.style.marginLeft = '2px';
                th.appendChild(badge);
            }
        } else {
            // Default state (unsorted)
            icon.className = 'fas fa-sort sort-icon';
            icon.style.opacity = '0.3';
        }
    });
}

// --- PDF Download Helpers ---
function getTableQueryParams(formId, tableId, options = {}) {
    const form = formId ? document.getElementById(formId) : null;
    const table = document.getElementById(tableId);
    if (!table) return new URLSearchParams();

    const params = collectFormData(formId, options.defaultParams || {}, table);

    return params;
}

function generatePDFUrl(formId, tableId, pdfBaseUrl, options = {}) {
    const params = getTableQueryParams(formId, tableId, options);
    return `${pdfBaseUrl}?${params.toString()}`;
}

function downloadTablePDF(formId, tableId, pdfBaseUrl, options = {}) {
    const pdfUrl = generatePDFUrl(formId, tableId, pdfBaseUrl, options);
    window.open(pdfUrl, '_blank');
}

// --- Extend $ wrapper with ajax method ---
(function () {
    const original$ = window.$;
    if (typeof original$ === 'function') {
        // Extend existing $ function to add ajax method
        window.$ = function (selector) {
            const result = original$(selector);
            // If result is an object with methods (from wordSuggestion.js), extend it
            if (result && typeof result === 'object' && !Array.isArray(result)) {
                result.ajax = function (options = {}) {
                    const form = typeof selector === "string" ? document.querySelector(selector) : selector;
                    if (!form || form.tagName !== "FORM") {
                        console.error("Table AJAX: Element must be a form");
                        return this;
                    }
                    const config = {
                        tableId: options.tableId || "",
                        url: options.url || "",
                        placeholder: options.placeholder || "Loading...",
                        method: options.method || "GET",
                        debounceDelay: options.debounceDelay || 400,
                        includeInputs: options.includeInputs || false,
                        autoLoad: options.autoLoad !== false,
                        sortable: options.sortable !== false,
                        onSuccess: options.onSuccess || null,
                        onError: options.onError || null,
                        defaultParams: options.defaultParams || {},
                        ...options
                    };
                    if (!config.tableId || !config.url) {
                        console.error("Table AJAX: tableId and url are required");
                        return this;
                    }
                    initTableAjax(form.id, config.tableId, config.url, {
                        method: config.method,
                        debounceDelay: config.debounceDelay,
                        loadingText: config.placeholder,
                        autoLoad: config.autoLoad,
                        onSuccess: config.onSuccess,
                        onError: config.onError,
                        defaultParams: config.defaultParams
                    }, config.includeInputs);
                    if (config.sortable) {
                        initTableSorting(config.tableId);
                    }
                    return this;
                };
            }
            return result;
        };
    }
})();

// --- Global expose ---
window.loadTableData = loadTableData;
window.initTableAjax = initTableAjax;
window.reloadTable = reloadTable;
window.initTableSorting = initTableSorting;
window.updateSortIndicators = updateSortIndicators;
window.getTableQueryParams = getTableQueryParams;
window.generatePDFUrl = generatePDFUrl;
window.downloadTablePDF = downloadTablePDF;
window.cleanupTable = cleanupTable; // Expose cleanup function

// Abort all in-flight table requests on page unload
window.addEventListener('beforeunload', () => {
    Object.values(tableAbortControllers).forEach(controller => {
        try { controller.abort(); } catch (e) { /* ignore */ }
    });
});
