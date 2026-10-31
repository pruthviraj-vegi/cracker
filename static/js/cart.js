/**
 * Optimized CartManager
 * Handles cart CRUD, barcode scanning, and real-time totals
 * Optimized for performance, readability, and maintainability
 */

class CartManager {
    // Constants for timing and configuration
    static DOM_READY_DELAY = 50;
    static ANIMATION_DURATION = 300;
    static DEBOUNCE_DELAY = 300;
    static REDIRECT_DELAY = 1500;
    static RETRY_ATTEMPTS = 3;
    static RETRY_DELAY = 1000;
    constructor() {
        this.initGlobals();
        this.initDOM();
        this.initListeners();
        this.focusBarcode();

        // Request management
        this.abortControllers = new Map();  // Per-endpoint abort controllers
        this.pendingRequests = new Set();
        this.isProcessingBarcode = false;

        // Offline detection
        this.isOnline = navigator.onLine;
        this.requestQueue = [];
        this.initOfflineDetection();

        // Debounced functions
        this.debouncedRecalculate = this.debounce(() => this.recalculateTotals(), 100);
        this.debouncedBarcodeSubmit = this.debounce((e) => this._handleBarcodeSubmit(e), 300);

        if (this.dom.totalSelling && this.dom.body) {
            setTimeout(() => this.recalculateTotals(), CartManager.DOM_READY_DELAY);
        }
    }

    /*** ───────── INITIALIZATION ───────── ***/
    /**
     * Initialize global configuration from window.CART_DATA
     * @private
     */
    initGlobals() {
        if (!window.CART_DATA) {
            console.error('[CartManager] CART_DATA missing. Make sure the template is properly loaded.');
            return;
        }

        const { CART_DATA } = window;
        this.csrf = CART_DATA.csrfToken;
        this.cartId = CART_DATA.cartId;
        this.urls = CART_DATA.urls;

        this.formatter = new Intl.NumberFormat('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    /**
     * Cache DOM elements for performance
     * @private
     */
    initDOM() {
        this.dom = {
            form: document.getElementById('barcodeForm'),
            input: document.getElementById('barcodeInput'),
            body: document.getElementById('cartItemsBody'),
            totalItems: document.getElementById('totalItems'),
            totalAmount: document.getElementById('totalAmount'),
            totalSelling: document.getElementById('totalSellingPrice'),
            archiveBtn: document.getElementById('archiveCartBtn'),
            clearBtn: document.getElementById('clearCartBtn'),
            priceHeader: document.getElementById('priceColumnHeader'),
            remainingStock: document.getElementById('remainingStock'),
            directPrintBtn: document.getElementById('directPrintEstimateBtn'),
        };

        // Initialize price toggle state (removed global pollution)
        this.priceToggleState = false;
    }

    initListeners() {
        const { form, body, archiveBtn, clearBtn, directPrintBtn } = this.dom;

        if (form) {
            form.addEventListener('submit', e => this.onBarcodeSubmit(e));
        }

        if (body) {
            body.addEventListener('click', e => this.onTableClick(e));
            body.addEventListener('keydown', e => this.onInputKey(e));
            body.addEventListener('focusin', e => this.onInputFocusIn(e));
            body.addEventListener('focusout', e => this.onRowFocusOut(e));
        }

        if (archiveBtn) {
            archiveBtn.addEventListener('click', () => {
                this.confirm('Archive Cart', 'Are you sure you want to archive this cart? This action cannot be undone.', () => this.archiveCart());
            });
        }

        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                this.confirm('Clear Cart', 'Are you sure you want to clear all items from this cart? This action cannot be undone.', () => this.clearCart());
            });
        }

        if (directPrintBtn) {
            directPrintBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.directPrintEstimate();
            });
        }

        this.initDropdown();
        this.initPriceToggle();
        this.initBarcodeSuggestions();
        this.initBarcodeScanner();
        this.initPriceSuggestionsBubble();

        // Cleanup in-flight requests on page unload
        window.addEventListener('beforeunload', () => {
            this.abortControllers.forEach(controller => controller.abort());
            this.abortControllers.clear();
        });
    }

    /**
     * Initialize price suggestion bubble show/hide logic on focus and hover
     * @private
     */
    initPriceSuggestionsBubble() {
        if (!this.dom.body) return;

        this.dom.body.addEventListener('focusin', (e) => {
            if (e.target.matches('.price-input')) {
                const container = e.target.closest('.price-bubble-container');
                const bubble = container?.querySelector('.price-suggestions-wrapper');
                if (bubble && bubble.children.length > 0) bubble.classList.remove('d-none');
            }
        });

        this.dom.body.addEventListener('focusout', (e) => {
            if (e.target.matches('.price-input')) {
                setTimeout(() => {
                    const container = e.target.closest('.price-bubble-container');
                    if (container && !container.contains(document.activeElement)) {
                        const bubble = container.querySelector('.price-suggestions-wrapper');
                        if (bubble) bubble.classList.add('d-none');
                    }
                }, 200);
            }
        });

    }

    /*** ───────── OFFLINE DETECTION ───────── ***/
    /**
     * Initialize offline detection and event listeners
     * @private
     */
    initOfflineDetection() {
        // Listen for online/offline events
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.notify('Connection restored', 'success');
            this.updateOfflineIndicator();
            this.processQueue();
        });

        window.addEventListener('offline', () => {
            this.isOnline = false;
            this.notify('You are offline. Changes will be queued.', 'warning');
            this.updateOfflineIndicator();
        });

        // Initial indicator update
        this.updateOfflineIndicator();
    }

    /**
     * Update visual offline indicator
     * @private
     */
    updateOfflineIndicator() {
        let indicator = document.getElementById('offlineIndicator');

        if (!this.isOnline) {
            if (!indicator) {
                indicator = document.createElement('div');
                indicator.id = 'offlineIndicator';
                indicator.style.cssText = `
                    position: fixed;
                    top: 10px;
                    right: 10px;
                    background: #ff9800;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    z-index: 9999;
                    font-size: 14px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                `;
                indicator.innerHTML = '<i class="fas fa-wifi" style="margin-right: 8px;"></i>Offline Mode';
                document.body.appendChild(indicator);
            }
        } else {
            if (indicator) {
                indicator.remove();
            }
        }
    }

    /**
     * Queue request for later execution when offline
     * @param {string} url - API endpoint
     * @param {string} method - HTTP method
     * @param {Object|null} body - Request body
     * @private
     */
    queueRequest(url, method, body) {
        this.requestQueue.push({ url, method, body, timestamp: Date.now() });
    }

    /**
     * Process queued requests when back online
     * @private
     */
    async processQueue() {
        if (this.requestQueue.length === 0) return;

        this.notify(`Processing ${this.requestQueue.length} queued request(s)...`, 'info');
        const queue = [...this.requestQueue];
        this.requestQueue = [];

        for (const request of queue) {
            try {
                await this.api(request.url, request.method, request.body);
            } catch (err) {
                console.error('[CartManager] Failed to process queued request:', err);
                // Re-queue failed requests
                this.requestQueue.push(request);
            }
        }

        if (this.requestQueue.length === 0) {
            this.notify('All queued requests processed', 'success');
            // Refresh the page to sync with server
            setTimeout(() => window.location.reload(), 1000);
        }
    }



    /*** ───────── HELPERS ───────── ***/
    /**
     * Show stock warning if stock is low or negative
     * @param {number} remainingStock - Remaining stock quantity
     * @param {string} productName - Product name for context
     * @private
     */
    showStockWarning(remainingStock, productName = 'Product') {
        if (remainingStock === undefined || remainingStock === null) return;

        if (remainingStock < 0) {
            this.notify(`Warning: ${productName} is oversold (stock: ${remainingStock})`, 'warning');
        }
    }

    /**
     * Debounce utility to limit function execution frequency
     * @param {Function} func - Function to debounce
     * @param {number} wait - Delay in milliseconds
     * @returns {Function} Debounced function
     * @private
     */
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    /**
     * Format number to Indian currency format
     * @param {number|string} num - Number to format
     * @returns {string} Formatted number string
     */
    format(num) {
        const n = typeof num === 'string' ? parseFloat(num.replace(/[^\d.-]/g, '')) : parseFloat(num);
        return isNaN(n) || !isFinite(n) ? '0.00' : this.formatter.format(n);
    }

    /**
     * Calculate discount percentage
     * @param {number} selling - Selling price
     * @param {number} price - Actual price
     * @returns {number} Discount percentage
     */
    calcDiscount(selling, price) {
        return selling > 0 ? Math.max(0, ((selling - price) / selling) * 100) : 0;
    }

    /**
     * Parse error message and provide context-specific feedback
     * @param {Error} err - Error object
     * @param {string} operation - Operation being performed
     * @returns {string} User-friendly error message
     * @private
     */
    parseErrorMessage(err, operation = 'operation') {
        const message = err.message || 'Unknown error';

        // Map common error patterns to user-friendly messages
        if (message.includes('NetworkError') || message.includes('Failed to fetch')) {
            return `Network error during ${operation}. Please check your connection.`;
        }
        if (message.includes('timeout')) {
            return `Request timed out during ${operation}. Please try again.`;
        }
        if (message.includes('401') || message.includes('Unauthorized')) {
            return `Session expired. Please refresh the page and log in again.`;
        }
        if (message.includes('403') || message.includes('Forbidden')) {
            return `You don't have permission to perform this ${operation}.`;
        }
        if (message.includes('404') || message.includes('Not Found')) {
            return `Item not found. It may have been deleted.`;
        }
        if (message.includes('500') || message.includes('Internal Server Error')) {
            return `Server error during ${operation}. Please contact support if this persists.`;
        }
        if (message.includes('failed after')) {
            return `${operation} failed after multiple attempts. Please try again later.`;
        }

        // Return original message if no pattern matches
        return `${operation} failed: ${message}`;
    }

    /**
     * Retry wrapper with exponential backoff
     * @param {Function} fn - Async function to retry
     * @param {number} attempt - Current attempt number
     * @returns {Promise<Object>} Result from function
     * @private
     */
    async retryWithBackoff(fn, attempt = 1) {
        try {
            return await fn();
        } catch (err) {
            // Don't retry if request was cancelled or if we've exhausted attempts
            if (err.message === 'Request cancelled' || attempt >= CartManager.RETRY_ATTEMPTS) {
                if (attempt >= CartManager.RETRY_ATTEMPTS) {
                    throw new Error(`${err.message} (failed after ${CartManager.RETRY_ATTEMPTS} attempts)`);
                }
                throw err;
            }

            // Exponential backoff: 1s, 2s, 4s
            const delay = CartManager.RETRY_DELAY * Math.pow(2, attempt - 1);
            await new Promise(resolve => setTimeout(resolve, delay));
            return this.retryWithBackoff(fn, attempt + 1);
        }
    }

    /**
     * Make API request with AbortController support and retry logic
     * @param {string} url - API endpoint
     * @param {string} method - HTTP method
     * @param {Object|null} body - Request body
     * @returns {Promise<Object>} API response data
     * @throws {Error} On network or API errors
     */
    async api(url, method = 'GET', body = null) {
        // Check if offline and queue request
        if (!this.isOnline) {
            this.queueRequest(url, method, body);
            throw new Error('You are offline. Request has been queued.');
        }

        return this.retryWithBackoff(async () => {
            // Cancel previous request for the SAME endpoint only
            const endpointKey = `${method}:${url}`;
            const existing = this.abortControllers.get(endpointKey);
            if (existing) {
                existing.abort();
            }

            const controller = new AbortController();
            this.abortControllers.set(endpointKey, controller);
            const requestId = Date.now();
            this.pendingRequests.add(requestId);

            try {
                const opts = {
                    method,
                    headers: {
                        'X-CSRFToken': this.csrf,
                        'Content-Type': 'application/json',
                    },
                    signal: controller.signal,
                };
                if (body) opts.body = JSON.stringify(body);

                const res = await fetch(url, opts);
                const data = await res.json();

                if (!res.ok || data.status === 'error') {
                    throw new Error(data.message || res.statusText || `HTTP ${res.status}`);
                }

                return data;
            } catch (err) {
                if (err.name === 'AbortError') {
                    throw new Error('Request cancelled');
                }
                console.error('[CartManager] API Error:', err);
                throw err;
            } finally {
                this.pendingRequests.delete(requestId);
                this.abortControllers.delete(endpointKey);
            }
        });
    }

    /**
     * Focus barcode input only if user is not actively typing elsewhere.
     * Skips auto-focus on mobile/touch devices to prevent keyboard/camera popup.
     */
    focusBarcode() {
        // Skip auto-focus on mobile/touch devices to prevent keyboard popup
        const isMobile = window.matchMedia('(max-width: 768px)').matches
            || ('ontouchstart' in window);
        if (isMobile) return;

        // Check if user is currently focused on an input element
        const activeElement = document.activeElement;
        const isTypingElsewhere = activeElement &&
            (activeElement.tagName === 'INPUT' ||
                activeElement.tagName === 'TEXTAREA' ||
                activeElement.isContentEditable);

        // Only auto-focus if user is not typing elsewhere
        if (!isTypingElsewhere) {
            this.dom.input?.focus();
        }
    }

    /**
     * Show notification to user
     * @param {string} msg - Notification message
     * @param {string} type - Notification type (info, success, error, warning)
     */
    notify(msg, type = 'info') {
        if (typeof showNotification === 'function') {
            showNotification(msg, type);
        }
    }

    /*** ───────── PRICE TOGGLE ───────── ***/
    /**
     * Initialize price toggle functionality (F9 key)
     * @private
     */
    initPriceToggle() {
        const hideProfitRowInitially = () => {
            const profitRow = document.getElementById('profitRow');
            if (profitRow) {
                profitRow.classList.remove('is-visible');
                profitRow.style.setProperty('display', 'none', 'important');
            }
        };

        // Initialize price display format after DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                hideProfitRowInitially();
                this.formatPriceDisplays();
                this.initProfitRowClickListener();
            });
        } else {
            // DOM already loaded
            hideProfitRowInitially();
            setTimeout(() => {
                hideProfitRowInitially();
                this.formatPriceDisplays();
                this.initProfitRowClickListener();
            }, CartManager.DOM_READY_DELAY);
        }

        // Listen for F9 key press
        document.addEventListener('keydown', (e) => {
            if (e.keyCode === 120 || e.key === 'F9') {
                e.preventDefault();
                this.togglePriceDisplay();
            }
        });
    }

    initProfitRowClickListener() {
        const profitRow = document.getElementById('profitRow');
        if (profitRow) {
            profitRow.addEventListener('click', () => {
                this.togglePriceDisplay();
            });
        }
    }

    formatPriceDisplays() {
        const priceCells = document.querySelectorAll('.price-toggle-cell .price-display');
        priceCells.forEach(span => {
            const value = parseFloat(span.textContent.replace(/[^\d.-]/g, '')) || 0;
            span.textContent = this.formatPriceAnimation(value);
        });
    }

    formatPriceAnimation(value) {
        return value.toLocaleString('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    animatePriceChange(element, _startValue, endValue, _duration = CartManager.ANIMATION_DURATION) {
        element.textContent = this.formatPriceAnimation(endValue);
    }

    /**
     * Toggle between selling price and purchase price display
     * Triggered by F9 key
     */
    togglePriceDisplay() {
        this.priceToggleState = !this.priceToggleState;

        const header = this.dom.priceHeader;
        const priceCells = document.querySelectorAll('.price-toggle-cell');

        // Update header
        if (header) {
            header.textContent = this.priceToggleState ? 'Purchase Price' : 'Selling Price';
        }

        // Update all price cells
        priceCells.forEach(cell => {
            const sellingPrice = parseFloat(cell.getAttribute('data-selling-price')) || 0;
            const purchasePrice = parseFloat(cell.getAttribute('data-purchase-price')) || 0;
            const displaySpan = cell.querySelector('.price-display');

            if (displaySpan) {
                const targetPrice = this.priceToggleState ? purchasePrice : sellingPrice;
                // Get current displayed value (remove currency symbols and parse)
                const currentText = displaySpan.textContent.replace(/[^\d.-]/g, '');
                const currentPrice = parseFloat(currentText) || 0;

                // Animate the price change
                this.animatePriceChange(displaySpan, currentPrice, targetPrice, CartManager.ANIMATION_DURATION);
            }
        });

        // Toggle profit row visibility
        const profitRow = document.getElementById('profitRow');
        if (profitRow) {
            if (this.priceToggleState) {
                profitRow.classList.add('is-visible');
                profitRow.style.setProperty('display', 'flex', 'important');
            } else {
                profitRow.classList.remove('is-visible');
                profitRow.style.setProperty('display', 'none', 'important');
            }
        }
    }

    /*** ───────── UI EVENTS ───────── ***/
    /**
     * Handle barcode form submission with debouncing to prevent race conditions
     * @param {Event} e - Submit event
     */
    async onBarcodeSubmit(e) {
        e.preventDefault();

        if (typeof this.closeBarcodeSuggestions === 'function') {
            this.closeBarcodeSuggestions();
        }

        // Prevent rapid successive scans (race condition fix)
        if (this.isProcessingBarcode) {
            return;
        }

        const code = this.dom.input.value.trim();

        // Input validation
        if (!code) {
            this.notify('Please enter a barcode', 'error');
            this.focusBarcode();
            return;
        }

        this.isProcessingBarcode = true;

        try {
            const data = await this.api(this.urls.scanBarcode, 'POST', {
                barcode: code,
                cart_id: Number(this.cartId),
                quantity: 1,
            });

            if (data.status !== 'success') {
                this.notify(data.message || 'Failed to add item', 'error');
                return;
            }

            this.dom.input.value = '';

            if (!data.cart_item) {
                this.notify('Invalid response structure', 'error');
                return;
            }

            if (data.type === 'Add' || data.type === 'Create') {
                this.addCartRow(data.cart_item);
                this.notify('Item added successfully', 'success');
            } else if (data.type === 'Update') {
                this.updateCartRow(data.cart_item);
                this.notify('Item updated successfully', 'success');
            }

            // Update totals (removed duplicate call)
            if (data.cart_total !== undefined) {
                this.updateTotals(data.cart_total);
            }

            if (data.remaining_stock !== undefined) {
                this.dom.remainingStock.textContent = data.remaining_stock;
                // Show stock warning (non-blocking)
                const productName = data.cart_item?.product_variant?.simple_name || 'Product';
                this.showStockWarning(data.remaining_stock, productName);
            }

            // Update categories
            if (data.category_counts) {
                this.updateCategories(data.category_counts);
            }
        } catch (err) {
            if (err.message !== 'Request cancelled') {
                console.error('[CartManager] Error in barcode submission:', err);
                this.notify(`Error adding product to cart: ${err.message}`, 'error');
            }
        } finally {
            this.isProcessingBarcode = false;
            this.focusBarcode();
        }
    }

    onInputKey(e) {
        if (e.key === 'Enter' && e.target.matches('.quantity-input, .price-input')) {
            e.preventDefault();
            const itemId = e.target.dataset.itemId;
            if (itemId) {
                this.updateItem(itemId);
            }
        }
    }

    onInputFocusIn(e) {
        const el = e.target;
        if (!el.matches('.quantity-input, .price-input')) return;

        const row = el.closest('tr');
        if (!row) return;

        const qtyInput = row.querySelector('.quantity-input');
        const priceInput = row.querySelector('.price-input');

        if (row.dataset.savedQty === undefined && qtyInput) {
            row.dataset.savedQty = qtyInput.value;
        }
        if (row.dataset.savedPrice === undefined && priceInput) {
            row.dataset.savedPrice = priceInput.value;
        }
    }

    onRowFocusOut(e) {
        const el = e.target;
        if (!el.matches('.quantity-input, .price-input')) return;

        const row = el.closest('tr');
        if (!row) return;

        if (e.relatedTarget && e.relatedTarget.closest('tr') === row && e.relatedTarget.matches('.quantity-input, .price-input')) {
            return;
        }

        const qtyInput = row.querySelector('.quantity-input');
        const priceInput = row.querySelector('.price-input');
        if (!qtyInput || !priceInput) return;
        if (qtyInput.disabled || priceInput.disabled) return;

        if (row.dataset.savedQty === undefined) {
            row.dataset.savedQty = qtyInput.value;
        }
        if (row.dataset.savedPrice === undefined) {
            row.dataset.savedPrice = priceInput.value;
        }

        const currentQty = parseFloat(qtyInput.value);
        const currentPrice = parseFloat(priceInput.value);
        const savedQty = parseFloat(row.dataset.savedQty);
        const savedPrice = parseFloat(row.dataset.savedPrice);

        if (isNaN(currentQty) || isNaN(currentPrice) || currentQty !== savedQty || currentPrice !== savedPrice) {
            const itemId = qtyInput.dataset.itemId || priceInput.dataset.itemId;
            if (itemId) {
                this.updateItem(itemId);
            }
        }
    }

    onTableClick(e) {
        const bubbleChip = e.target.closest('.suggestion-bubble');
        if (bubbleChip) {
            e.preventDefault();
            const targetPrice = bubbleChip.dataset.price;
            if (targetPrice === undefined || targetPrice === null) return;

            const row = bubbleChip.closest('tr');
            if (!row) return;

            const priceInput = row.querySelector('.price-input');
            if (priceInput) {
                const numericPrice = parseFloat(targetPrice) || 0;
                priceInput.value = numericPrice;

                // Hide floating wrapper if present
                const bubble = bubbleChip.closest('.price-suggestions-wrapper');
                if (bubble) bubble.classList.add('d-none');

                // Save item change via API
                const itemId = priceInput.dataset.itemId;
                if (itemId) {
                    this.updateItem(itemId);
                }
            }
            return;
        }

        const btn = e.target.closest('.update-item-btn, .delete-item-btn');
        if (!btn) return;

        const itemId = btn.dataset.itemId;
        if (!itemId) return;

        if (btn.classList.contains('update-item-btn')) {
            this.updateItem(itemId);
        } else if (btn.classList.contains('delete-item-btn')) {
            this.deleteItem(itemId);
        }
    }

    /*** ───────── CRUD OPS ───────── ***/
    /**
     * Update cart item after successful API response
     * @param {string|number} id - Cart item ID
     */
    async updateItem(id) {
        const row = document.getElementById(`cart-item-${id}`);
        if (!row) {
            return this.notify('Item not found', 'error');
        }

        const qtyInput = row.querySelector('.quantity-input');
        const priceInput = row.querySelector('.price-input');
        const amountCell = row.querySelector('.amount-cell');
        const discountCell = row.querySelector('.discount-cell');
        const priceToggleCell = row.querySelector('.price-toggle-cell');

        if (!qtyInput || !priceInput || !amountCell) {
            return this.notify('Invalid form inputs', 'error');
        }

        const qty = parseFloat(qtyInput.value);
        const price = parseFloat(priceInput.value);

        // Enhanced validation
        if (isNaN(qty) || isNaN(price) || qty <= 0 || price < 0) {
            if (row.dataset.savedQty !== undefined) qtyInput.value = row.dataset.savedQty;
            if (row.dataset.savedPrice !== undefined) priceInput.value = row.dataset.savedPrice;
            return this.notify('Please enter valid quantity and price (quantity > 0, price ≥ 0)', 'error');
        }

        // Skip API call if values have not changed from saved state
        if (row.dataset.savedQty === undefined) row.dataset.savedQty = qtyInput.value;
        if (row.dataset.savedPrice === undefined) row.dataset.savedPrice = priceInput.value;

        const savedQty = parseFloat(row.dataset.savedQty);
        const savedPrice = parseFloat(row.dataset.savedPrice);

        if (!isNaN(savedQty) && !isNaN(savedPrice) && qty === savedQty && price === savedPrice) {
            return;
        }

        // Disable inputs during update to prevent duplicate submissions
        qtyInput.disabled = true;
        priceInput.disabled = true;

        const btn = row.querySelector('.update-item-btn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        }

        try {
            const data = await this.api(this.urls.manageItem.replace('0', id), 'PUT', { quantity: qty, price });

            // Update UI ONLY after verified successful API response
            if (data.status === 'success' && data.cart_item) {
                // Update inputs and dataset from response
                qtyInput.value = data.cart_item.quantity;
                priceInput.value = data.cart_item.price;
                row.dataset.savedQty = data.cart_item.quantity;
                row.dataset.savedPrice = data.cart_item.price;

                if (amountCell) {
                    amountCell.textContent = this.format(data.cart_item.amount);
                }

                // Update discount percentage
                if (discountCell) {
                    if (data.cart_item.discount_percentage !== undefined) {
                        discountCell.textContent = `${data.cart_item.discount_percentage}`;
                    } else {
                        const sellingPrice = parseFloat(priceToggleCell?.dataset.sellingPrice) || 0;
                        const discount = this.calcDiscount(sellingPrice, data.cart_item.price);
                        discountCell.textContent = `${discount.toFixed(2)}`;
                    }
                }

                if (data.remaining_stock !== undefined && this.dom.remainingStock) {
                    this.dom.remainingStock.textContent = this.format(data.remaining_stock);
                }

                // Update totals and recalculate sidebar
                this.updateTotals(data.cart_total);

                // Update categories
                if (data.category_counts) {
                    this.updateCategories(data.category_counts);
                }

                this.notify('Item updated successfully', 'success');
            } else {
                throw new Error(data.message || 'Failed to update item');
            }
        } catch (err) {
            if (err.message !== 'Request cancelled') {
                console.error('[CartManager] Error updating item:', err);
                this.notify(this.parseErrorMessage(err, 'update'), 'error');

                // Revert inputs to last saved values on failure
                if (row.dataset.savedQty !== undefined) {
                    qtyInput.value = row.dataset.savedQty;
                }
                if (row.dataset.savedPrice !== undefined) {
                    priceInput.value = row.dataset.savedPrice;
                }
            }
        } finally {
            qtyInput.disabled = false;
            priceInput.disabled = false;
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-save" aria-hidden="true"></i>';
            }
            this.focusBarcode();
        }
    }

    /**
     * Delete cart item with confirmation
     * @param {string|number} id - Cart item ID
     */
    async deleteItem(id) {
        // Use custom modal for consistency
        this.confirm(
            'Remove Item',
            'Are you sure you want to remove this item from the cart?',
            () => this.performDelete(id)
        );
    }

    /**
     * Perform the actual delete operation
     * @param {string|number} id - Cart item ID
     * @private
     */
    async performDelete(id) {
        const row = document.getElementById(`cart-item-${id}`);
        if (!row) {
            return this.notify('Item not found', 'error');
        }

        try {
            // Delete from backend immediately
            const data = await this.api(this.urls.manageItem.replace('0', id), 'DELETE');

            if (data.status === 'success') {
                // Remove from DOM
                row.remove();

                // Update totals
                this.updateTotals(data.cart_total);

                // Update categories
                if (data.category_counts) {
                    this.updateCategories(data.category_counts);
                }

                this.notify('Item removed successfully', 'success');
            } else {
                this.notify(data.message || 'Failed to delete item', 'error');
            }
        } catch (err) {
            console.error('[CartManager] Error deleting item:', err);
            this.notify(this.parseErrorMessage(err, 'delete'), 'error');
        } finally {
            this.focusBarcode();
        }
    }

    /*** ───────── UI UPDATES ───────── ***/
    /**
     * Update existing cart row with new item data
     * @param {Object} item - Cart item data
     */
    updateCartRow(item) {
        const row = document.getElementById(`cart-item-${item.id}`);
        if (!row) {
            return this.addCartRow(item);
        }

        const qtyInput = row.querySelector('.quantity-input');
        const priceInput = row.querySelector('.price-input');
        const amountCell = row.querySelector('.amount-cell');
        const discountCell = row.querySelector('.discount-cell');
        const priceToggleCell = row.querySelector('.price-toggle-cell');

        if (qtyInput) qtyInput.value = item.quantity;
        if (priceInput) priceInput.value = item.price;
        if (amountCell) amountCell.textContent = this.format(item.amount);

        row.dataset.savedQty = item.quantity;
        row.dataset.savedPrice = item.price;

        if (discountCell) {
            if (item.discount_percentage !== undefined) {
                discountCell.textContent = `${item.discount_percentage}`;
            } else {
                const selling = parseFloat(priceToggleCell?.dataset.sellingPrice) || 0;
                const discount = this.calcDiscount(selling, item.price);
                discountCell.textContent = `${discount.toFixed(2)}`;
            }
        }

        this.recalculateTotals();
    }

    /**
     * Add new cart row to the table
     * @param {Object} data - Cart item data with product variant information
     */
    addCartRow(data) {
        const {
            id,
            quantity,
            price,
            amount,
            product_variant: {
                barcode = 'N/A',
                product_name = "N/A",
                simple_name: variantName = 'N/A',
                mrp: sellingPrice = data.price || '0.00',
                purchase_price: purchasePrice = '0.00',
                final_price: finalPrice = data.product_variant?.final_price || sellingPrice,
                discount_percentage: discount = 0,
                frequent_sold_prices: frequentSoldPrices = [],
            } = {},
        } = data;

        const brand = product_name || 'N/A';
        const safeBarcode = typeof escapeHtml === 'function' ? escapeHtml(String(barcode)) : String(barcode).replace(/[<>&"']/g, '');
        const safeBrand = typeof escapeHtml === 'function' ? escapeHtml(String(brand)) : String(brand).replace(/[<>&"']/g, '');
        const safeVariantName = typeof escapeHtml === 'function' ? escapeHtml(String(variantName)) : String(variantName).replace(/[<>&"']/g, '');

        let calculatedDiscount = data.discount_percentage;
        if (calculatedDiscount === undefined || calculatedDiscount === null) {
            calculatedDiscount = discount;
            if (sellingPrice > 0 && data.price) {
                calculatedDiscount = this.calcDiscount(sellingPrice, data.price);
            }
        }

        const isShowingPurchasePrice = this.priceToggleState;
        const displayPrice = isShowingPurchasePrice ? parseFloat(purchasePrice) : parseFloat(sellingPrice);
        const priceDisplay = this.formatPriceAnimation(displayPrice);

        // Build price suggestion chips for floating bubble
        let chipsHtml = ``;

        if (frequentSoldPrices && frequentSoldPrices.length > 0) {
            frequentSoldPrices.forEach(p => {
                chipsHtml += `
                <div class="suggestion-bubble" data-price="${p}" title="Set Past Sold Price">
                    ${this.format(p)}
                </div>`;
            });
        }

        const row = document.createElement('tr');
        row.id = `cart-item-${id}`;
        row.dataset.savedQty = quantity;
        row.dataset.savedPrice = price;
        row.innerHTML = `
            <td class="mobile-hide">
                <span data-copy="${safeBarcode}">${safeBarcode}</span>
            </td>
            <td>
                <div>
                    <span class="font-weight-bold">${safeBrand}</span>
                    <span class="mobile-inline text-muted small"> · ${safeVariantName}</span>
                </div>
            </td>
            <td class="mobile-hide">${safeVariantName}</td>
            <td class="price-toggle-cell text-end"
                data-selling-price="${sellingPrice}"
                data-purchase-price="${purchasePrice}">
                <span class="price-display">${priceDisplay}</span>
            </td>
            <td class="text-end">
                <input type="number" class="form-input quantity-input" value="${quantity}"
                       data-item-id="${id}" min="1" step="1"
                       title="Press Enter to update" aria-label="Quantity">
            </td>
            <td class="text-end">
                <div class="price-bubble-container" style="position: relative;">
                    <input type="number" class="form-input price-input" value="${price}" 
                           data-item-id="${id}"
                           min="0" step="1" 
                           title="Press Enter to update" aria-label="Selling Price">
                    <div class="price-suggestions-wrapper d-none">
                        ${chipsHtml}
                    </div>
                </div>
            </td>
            <td class="discount-cell mobile-hide text-end">${calculatedDiscount.toFixed(2)}</td>
            <td class="amount-cell text-end">${this.format(amount)}</td>
            <td class="text-center">
                <div class="action-buttons d-inline-flex flex-nowrap align-items-center justify-content-center gap-1">
                    <button type="button" class="btn btn-danger delete-item-btn" data-item-id="${id}"
                            tabindex="-1" title="Remove item" aria-label="Remove item from cart">
                        <i class="fas fa-trash" aria-hidden="true"></i>
                    </button>
                </div>
            </td>
        `;

        // Add new items at the top
        if (this.dom.body.firstChild) {
            this.dom.body.insertBefore(row, this.dom.body.firstChild);
        } else {
            this.dom.body.appendChild(row);
        }

        this.recalculateTotals();
    }

    /**
     * Update total amount displays
     * @param {number} total - New total amount
     */
    updateTotals(total) {
        if (this.dom.totalAmount) {
            const num = parseFloat(total) || 0;
            this.dom.totalAmount.setAttribute('data-count', num.toFixed(2));
            this.dom.totalAmount.textContent = this.format(num);
        }
        // Recalculate derived totals (quantity, selling price, actual total, discount, profit, net amount)
        this.recalculateTotals();
    }

    /**
     * Unified method to recalculate all totals (quantity, selling price, actual total, and final amount)
     * More efficient than separate methods - single DOM scan
     */
    recalculateTotals() {
        if (!this.dom.body) return;

        const rows = this.dom.body.querySelectorAll('tr');

        if (rows.length === 0) {
            if (this.dom.totalAmount) {
                this.dom.totalAmount.setAttribute('data-count', '0.00');
                this.dom.totalAmount.textContent = this.format(0);
            }
            if (typeof updateAllCounters === 'function') {
                updateAllCounters({
                    totalItems: 0,
                    totalSellingPrice: 0,
                    discountedAmount: 0,
                    estimatedProfit: 0,
                    netAmount: 0
                });
            } else {
                if (this.dom.totalItems) this.dom.totalItems.textContent = '0';
                if (this.dom.totalSelling) this.dom.totalSelling.textContent = this.format(0);
                if (this.dom.totalAmount) this.dom.totalAmount.textContent = this.format(0);
                const discountedAmountEl = document.getElementById('discountedAmount');
                if (discountedAmountEl) discountedAmountEl.textContent = this.format(0);
                const estimatedProfitEl = document.getElementById('estimatedProfit');
                if (estimatedProfitEl) estimatedProfitEl.textContent = this.format(0);
                const netAmountEl = document.getElementById('netAmount');
                if (netAmountEl) netAmountEl.textContent = this.format(0);
            }
            const cartButtonTotal = document.getElementById(`cart-button-total-${this.cartId}`);
            if (cartButtonTotal) cartButtonTotal.textContent = this.format(0);
            const cartListTotal = document.getElementById(`cart-list-total-${this.cartId}`);
            if (cartListTotal) cartListTotal.textContent = this.format(0);
            return;
        }

        // Batch reads first (no writes interleaved)
        const rowData = Array.from(rows).map(row => {
            const qtyInput = row.querySelector('.quantity-input');
            const priceToggleCell = row.querySelector('.price-toggle-cell');
            const priceInput = row.querySelector('.price-input');
            if (!qtyInput || !priceToggleCell) return null;
            return {
                qty: parseFloat(qtyInput.value) || 0,
                sell: parseFloat(priceToggleCell.dataset.sellingPrice) || 0,
                purchase: parseFloat(priceToggleCell.dataset.purchasePrice) || 0,
                actualPrice: priceInput ? parseFloat(priceInput.value) || 0 : parseFloat(priceToggleCell.dataset.sellingPrice) || 0,
            };
        });

        // Then compute from present/updated row values
        let totalQty = 0;
        let totalSelling = 0;
        let totalActualAmount = 0;
        let totalProfit = 0;

        rowData.forEach(d => {
            if (!d) return;
            if (!isNaN(d.qty)) totalQty += d.qty;
            if (!isNaN(d.qty) && !isNaN(d.sell) && d.qty > 0 && d.sell > 0) totalSelling += d.qty * d.sell;
            if (!isNaN(d.qty) && !isNaN(d.actualPrice) && d.qty > 0) totalActualAmount += d.qty * d.actualPrice;
            if (!isNaN(d.qty) && !isNaN(d.purchase) && d.qty > 0) totalProfit += d.qty * (d.actualPrice - d.purchase);
        });

        // Round and format
        const roundedQty = Math.round(totalQty * 100) / 100;
        const roundedSelling = Math.round(totalSelling * 100) / 100;
        const roundedActual = Math.round(totalActualAmount * 100) / 100;
        const roundedProfit = Math.round(totalProfit * 100) / 100;

        // Update hidden totalAmount element tracking
        if (this.dom.totalAmount) {
            this.dom.totalAmount.setAttribute('data-count', roundedActual.toFixed(2));
            this.dom.totalAmount.textContent = this.format(roundedActual);
        }

        const advancePaymentEl = document.getElementById('advancePayment');
        const advance = advancePaymentEl ? parseFloat(advancePaymentEl.dataset.advance || '0') || 0 : 0;

        const discount = Math.max(0, roundedSelling - roundedActual);
        const netAmount = Math.max(0, roundedActual - advance);

        if (typeof updateCount === 'function') {
            updateCount('totalItems', roundedQty);
            updateCount('totalSellingPrice', roundedSelling);
            updateCount('discountedAmount', discount);
            updateCount('estimatedProfit', roundedProfit);
            updateCount('netAmount', netAmount);
        } else {
            if (this.dom.totalItems) this.dom.totalItems.textContent = roundedQty.toFixed(2);
            if (this.dom.totalSelling) this.dom.totalSelling.textContent = this.format(roundedSelling);
            const discountedAmountEl = document.getElementById('discountedAmount');
            if (discountedAmountEl) discountedAmountEl.textContent = this.format(discount);
            const estimatedProfitEl = document.getElementById('estimatedProfit');
            if (estimatedProfitEl) estimatedProfitEl.textContent = this.format(roundedProfit);
            const netAmountEl = document.getElementById('netAmount') || document.getElementById('finalAmount');
            if (netAmountEl) netAmountEl.textContent = this.format(netAmount);
        }

        const cartButtonTotal = document.getElementById(`cart-button-total-${this.cartId}`);
        if (cartButtonTotal) {
            const advanceText = advance > 0 ? ` (${this.format(advance)})` : '';
            cartButtonTotal.textContent = `${this.format(roundedActual)}${advanceText}`;
        }
        const cartListTotal = document.getElementById(`cart-list-total-${this.cartId}`);
        if (cartListTotal) {
            const advanceText = advance > 0 ? ` (${this.format(advance)})` : '';
            cartListTotal.textContent = `${this.format(roundedActual)}${advanceText}`;
        }
    }

    /**
     * Update category summaries from API response data
     * @param {Array} categories - Array of {category_name, total_qty} objects
     */
    updateCategories(categories) {
        const body = document.getElementById('categoriesBody');
        if (!body) return;

        body.innerHTML = '';

        if (!categories || categories.length === 0) {
            const row = document.createElement('div');
            row.className = 'summary-row';
            row.innerHTML = '<span class="summary-label text-muted">No items</span>';
            body.appendChild(row);
            return;
        }

        categories.forEach(cat => {
            const row = document.createElement('div');
            row.className = 'summary-row category-summary-row';
            row.dataset.category = cat.category_name;
            const safeName = typeof escapeHtml === 'function' ? escapeHtml(String(cat.category_name)) : String(cat.category_name).replace(/[<>&"']/g, '');
            row.innerHTML = `
                <span class="summary-label">${safeName}</span>
                <span class="summary-value">${cat.total_qty}</span>
            `;
            body.appendChild(row);
        });
    }
    /**
     * @deprecated This method is kept for backward compatibility only.
     * Use recalculateTotals() for UI updates. This will be removed in future versions.
     * @returns {Object} Object containing totalItems, totalQuantity, and quantity arrays
     */
    calculateTotals() {
        if (!this.dom.body) {
            return { totalItems: 0, totalQuantity: 0, quantityInputs: [], quantities: [] };
        }

        const rows = this.dom.body.querySelectorAll('tr');
        const allQuantityInputs = this.dom.body.querySelectorAll('.quantity-input');
        const quantityInputsArray = Array.from(allQuantityInputs);

        const quantities = quantityInputsArray.map(input => parseFloat(input.value) || 0);
        const totalQuantity = quantities.reduce((sum, qty) => sum + qty, 0);

        return {
            totalItems: rows.length,
            totalQuantity,
            quantityInputs: quantityInputsArray,
            quantities,
        };
    }

    rollbackItemUpdate(itemId, originalValues) {
        if (!originalValues) return;

        const row = document.getElementById(`cart-item-${itemId}`);
        if (!row) {
            console.warn(`Rollback failed: Item ${itemId} not found`);
            return;
        }

        const qtyInput = row.querySelector('.quantity-input');
        const priceInput = row.querySelector('.price-input');
        const amountCell = row.querySelector('.amount-cell');
        const discountCell = row.querySelector('.discount-cell');

        if (qtyInput && originalValues.quantity) {
            qtyInput.value = originalValues.quantity;
            row.dataset.savedQty = originalValues.quantity;
        }
        if (priceInput && originalValues.price) {
            priceInput.value = originalValues.price;
            row.dataset.savedPrice = originalValues.price;
        }
        if (amountCell && originalValues.amount) {
            amountCell.textContent = originalValues.amount;
        }
        if (discountCell && originalValues.discount) {
            discountCell.textContent = originalValues.discount;
        }
        if (originalValues.totalAmount) {
            this.dom.totalAmount.textContent = originalValues.totalAmount;
            // Also update cart button total
            const cartButtonTotal = document.getElementById(`cart-button-total-${this.cartId}`);
            if (cartButtonTotal) {
                cartButtonTotal.textContent = originalValues.totalAmount;
            }
        }

        console.warn(`Rolled back update for item ${itemId}`);
        this.recalculateTotals();
    }

    /*** ───────── CART ACTIONS ───────── ***/
    /**
     * Archive current cart and redirect to cart list
     */
    async archiveCart() {
        // Disable buttons to prevent double-click
        if (this.dom.archiveBtn) {
            this.dom.archiveBtn.disabled = true;
            this.dom.archiveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Archiving...';
        }

        try {
            const data = await this.api(this.urls.archiveCart, 'POST');
            if (data.status === 'success') {
                this.notify('Cart archived successfully', 'success');
                setTimeout(() => (window.location.href = '/cart/'), CartManager.REDIRECT_DELAY);
            } else {
                this.notify(data.message || 'Failed to archive cart', 'error');
                if (this.dom.archiveBtn) {
                    this.dom.archiveBtn.disabled = false;
                    this.dom.archiveBtn.innerHTML = '<i class="fas fa-archive"></i> Archive Cart';
                }
            }
        } catch (err) {
            console.error('[CartManager] Error archiving cart:', err);
            this.notify('Failed to archive cart. Please try again.', 'error');
            if (this.dom.archiveBtn) {
                this.dom.archiveBtn.disabled = false;
                this.dom.archiveBtn.innerHTML = '<i class="fas fa-archive"></i> Archive Cart';
            }
        }
    }

    /**
     * Clear all items from current cart
     */
    async clearCart() {
        // Disable buttons to prevent double-click
        if (this.dom.clearBtn) {
            this.dom.clearBtn.disabled = true;
            this.dom.clearBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        }

        try {
            const data = await this.api(this.urls.clearCart, 'POST');
            if (data.status === 'success') {
                this.notify('Cart cleared successfully', 'success');
                if (this.dom.body) {
                    this.dom.body.innerHTML = '';
                }
                this.updateTotals(0);
                // Update categories
                if (data.category_counts !== undefined) {
                    this.updateCategories(data.category_counts);
                }
            } else {
                this.notify(data.message || 'Failed to clear cart', 'error');
            }
        } catch (err) {
            console.error('[CartManager] Error clearing cart:', err);
            this.notify('Failed to clear cart. Please try again.', 'error');
        } finally {
            // Re-enable button
            if (this.dom.clearBtn) {
                this.dom.clearBtn.disabled = false;
                this.dom.clearBtn.innerHTML = '<i class="fas fa-trash"></i>';
            }
        }
    }

    /**
     * Direct print estimate (cart) via network printer
     */
    async directPrintEstimate() {
        if (!this.dom.directPrintBtn) return;
        const btn = this.dom.directPrintBtn;
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);

        try {
            const url = btn.getAttribute('data-url');
            const res = await fetch(url, {
                method: 'GET',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': this.csrf,
                },
                signal: controller.signal,
            });
            const data = await res.json();
            if (res.ok && data.success) {
                this.notify(data.message || 'Estimate sent to printer successfully', 'success');
            } else {
                this.notify(data.error || 'Failed to print estimate', 'error');
            }
        } catch (err) {
            if (err.name === 'AbortError') {
                this.notify('Print request timed out', 'error');
            } else {
                console.error('[CartManager] Error printing estimate:', err);
                this.notify('Error communicating with printer', 'error');
            }
        } finally {
            clearTimeout(timeoutId);
            btn.disabled = false;
            btn.innerHTML = originalHtml;
            this.focusBarcode();
        }
    }

    /*** ───────── UI UTILITIES ───────── ***/
    /**
     * Show confirmation modal with custom message
     * @param {string} title - Modal title
     * @param {string} msg - Confirmation message
     * @param {Function} cb - Callback to execute on confirmation
     */
    confirm(title, msg, cb) {
        const modal = document.getElementById('confirmModal');
        if (!modal) {
            // Fallback to native confirm if modal not available
            if (window.confirm(`${title}\n\n${msg}`)) {
                cb();
            }
            return;
        }

        const modalTitle = modal.querySelector('.modal-title') || document.getElementById('confirmModalLabel');
        const modalBody = modal.querySelector('.modal-body') || document.getElementById('confirmModalBody');
        const confirmBtn = modal.querySelector('#confirmActionBtn') || document.getElementById('confirmActionBtn');

        if (!modalTitle || !modalBody || !confirmBtn) {
            // Fallback if modal structure is incomplete
            if (window.confirm(`${title}\n\n${msg}`)) {
                cb();
            }
            return;
        }

        modalTitle.textContent = title;
        modalBody.textContent = msg;

        // Remove previous event listener to prevent memory leak
        const newConfirmBtn = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);

        // Add new event listener
        newConfirmBtn.addEventListener('click', () => {
            cb();
            this.hideModal(modal);
        });

        // Show modal with Bootstrap or fallback
        this.showModal(modal);
    }

    /**
     * Show modal using Bootstrap or fallback
     * @param {HTMLElement} modal - Modal element
     * @private
     */
    showModal(modal) {
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            const bootstrapModal = new bootstrap.Modal(modal);
            bootstrapModal.show();
        } else {
            // Fallback: manual modal display
            modal.style.display = 'block';
            modal.classList.add('show');
            document.body.classList.add('modal-open');

            // Create backdrop
            const backdrop = document.createElement('div');
            backdrop.className = 'modal-backdrop fade show';
            backdrop.id = 'customModalBackdrop';
            document.body.appendChild(backdrop);
        }
    }

    /**
     * Hide modal using Bootstrap or fallback
     * @param {HTMLElement} modal - Modal element
     * @private
     */
    hideModal(modal) {
        if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
            const bootstrapModal = bootstrap.Modal.getInstance(modal);
            if (bootstrapModal) {
                bootstrapModal.hide();
            }
        } else {
            // Fallback: manual modal hide
            modal.style.display = 'none';
            modal.classList.remove('show');
            document.body.classList.remove('modal-open');

            // Remove backdrop
            const backdrop = document.getElementById('customModalBackdrop');
            if (backdrop) {
                backdrop.remove();
            }
        }
    }

    /*** ───────── BARCODE SUGGESTIONS ───────── ***/
    initBarcodeSuggestions() {
        const input = this.dom.input;
        const form = this.dom.form;
        const searchSection = document.querySelector('.search-filter-section');
        if (!input || !form) return;

        let debounceTimer = null;
        let isSelecting = false;
        let abortController = null;
        const queryCache = new Map();
        const MAX_QUERY_CACHE = 50;

        const dropdown = document.createElement('div');
        dropdown.id = 'barcodeSuggestions';
        dropdown.className = 'barcode-suggestions-dropdown';

        const backdrop = document.createElement('div');
        backdrop.className = 'suggestion-backdrop';
        document.body.appendChild(backdrop);

        backdrop.addEventListener('mousedown', () => {
            closeDropdown();
            input.blur();
        });

        input.parentElement.style.position = 'relative';
        input.parentElement.appendChild(dropdown);

        const self = this;

        function renderDropdown(items) {
            dropdown.innerHTML = '';
            if (!items.length) {
                dropdown.style.display = 'none';
                return;
            }

            items.forEach(item => {
                const row = document.createElement('div');
                row.className = 'suggestion-row';
                row.dataset.barcode = item.barcode;

                const variantParts = [item.color, item.size].filter(Boolean);
                const variantText = variantParts.join(' / ');
                const stockNum = parseFloat(item.stock);
                const isOutOfStock = !isNaN(stockNum) && stockNum <= 0;

                const productLabel = item.brand ? `${item.brand} - ${item.product}` : item.product;
                const finalPriceNum = parseFloat(item.final_price);
                const mrpNum = parseFloat(item.mrp);
                const discountNum = parseFloat(item.discount_percentage);
                const hasDiscount = !isNaN(finalPriceNum) && !isNaN(mrpNum) && finalPriceNum < mrpNum;

                const discountBadge = (!isNaN(discountNum) && discountNum > 0)
                    ? `<span class="suggestion-badge-discount">${Math.round(discountNum)}% OFF</span>`
                    : '';
                const stockBadge = isOutOfStock
                    ? `<span class="suggestion-badge-out">Out of Stock</span>`
                    : '';

                row.innerHTML = `
                    <div class="suggestion-header">
                        <div class="suggestion-title-wrap">
                            <span class="suggestion-product" title="${productLabel}">${productLabel}</span>
                            ${discountBadge}
                            ${stockBadge}
                        </div>
                        <div class="suggestion-price-wrap">
                            <span class="suggestion-price">${self.format(item.final_price || item.mrp)}</span>
                            ${hasDiscount ? `<span class="suggestion-mrp">${self.format(mrpNum)}</span>` : ''}
                        </div>
                    </div>
                    <div class="suggestion-meta">
                        <span class="suggestion-meta-item suggestion-barcode">
                            <i class="fas fa-barcode"></i> ${item.barcode}
                        </span>
                        ${variantText ? `<span class="suggestion-meta-item suggestion-variant">· ${variantText}</span>` : ''}
                        <span class="suggestion-meta-item suggestion-stock ${isOutOfStock ? 'stock-zero' : ''}">
                            · Qty: ${item.stock !== undefined ? item.stock : '—'}
                        </span>
                    </div>
                `;

                row.addEventListener('mouseenter', () => {
                    clearActiveHighlight();
                    row.classList.add('suggestion-active');
                });
                row.addEventListener('mouseleave', () => {
                    row.classList.remove('suggestion-active');
                });

                row.addEventListener('mousedown', (e) => {
                    e.preventDefault();
                    isSelecting = true;
                    selectSuggestion(item.barcode);
                });

                dropdown.appendChild(row);
            });

            dropdown.style.display = 'block';
            backdrop.classList.add('active');
            if (searchSection) searchSection.classList.add('suggestion-elevated');
        }

        function selectSuggestion(barcode) {
            closeDropdown();
            input.value = barcode;
            isSelecting = false;
            requestAnimationFrame(() => {
                form.requestSubmit();
            });
        }

        function closeDropdown() {
            clearTimeout(debounceTimer);
            if (abortController) {
                abortController.abort();
                abortController = null;
            }
            dropdown.style.display = 'none';
            dropdown.innerHTML = '';
            backdrop.classList.remove('active');
            if (searchSection) searchSection.classList.remove('suggestion-elevated');
        }

        self.closeBarcodeSuggestions = closeDropdown;

        function clearActiveHighlight() {
            dropdown.querySelectorAll('.suggestion-active').forEach(el => {
                el.classList.remove('suggestion-active');
            });
        }

        function fetchSuggestions(query) {
            const currentVal = input.value.trim();
            if (!currentVal || currentVal.length < 2 || currentVal !== query) {
                closeDropdown();
                return;
            }

            // Return from in-memory cache instantly if available
            const cacheKey = query.toLowerCase();
            if (queryCache.has(cacheKey)) {
                renderDropdown(queryCache.get(cacheKey));
                return;
            }

            if (abortController) {
                abortController.abort();
            }
            abortController = new AbortController();

            const url = `${self.urls.barcodeSuggestions}?search=${encodeURIComponent(query)}`;
            fetch(url, {
                signal: abortController.signal,
                headers: { 'X-CSRFToken': self.csrf }
            })
                .then(r => r.json())
                .then(items => {
                    // Update cache (LRU eviction if at limit)
                    if (queryCache.size >= MAX_QUERY_CACHE) {
                        const oldest = queryCache.keys().next().value;
                        queryCache.delete(oldest);
                    }
                    queryCache.set(cacheKey, items);

                    if (input.value.trim() !== query) {
                        closeDropdown();
                        return;
                    }
                    renderDropdown(items);
                })
                .catch(err => {
                    if (err && err.name === 'AbortError') {
                        return;
                    }
                    closeDropdown();
                });
        }

        input.addEventListener('input', function () {
            const val = this.value.trim();
            clearTimeout(debounceTimer);
            if (!val || val.length < 2) {
                closeDropdown();
                return;
            }
            debounceTimer = setTimeout(() => fetchSuggestions(val), CartManager.DEBOUNCE_DELAY);
        });

        input.addEventListener('focus', function () {
            if (!this.value.trim()) {
                closeDropdown();
            }
        });

        input.addEventListener('blur', function () {
            if (!isSelecting) closeDropdown();
        });

        input.addEventListener('keydown', function (e) {
            const rows = Array.from(dropdown.querySelectorAll('.suggestion-row'));
            if (!rows.length) return;

            const activeRow = dropdown.querySelector('.suggestion-active');
            const activeIdx = activeRow ? rows.indexOf(activeRow) : -1;

            if (e.key === 'Escape') {
                closeDropdown();
                return;
            }

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                const nextIdx = activeIdx < rows.length - 1 ? activeIdx + 1 : 0;
                clearActiveHighlight();
                rows[nextIdx].classList.add('suggestion-active');
                rows[nextIdx].scrollIntoView({ block: 'nearest' });
                return;
            }

            if (e.key === 'ArrowUp') {
                e.preventDefault();
                const prevIdx = activeIdx > 0 ? activeIdx - 1 : rows.length - 1;
                clearActiveHighlight();
                rows[prevIdx].classList.add('suggestion-active');
                rows[prevIdx].scrollIntoView({ block: 'nearest' });
                return;
            }

            if (e.key === 'Enter') {
                if (dropdown.style.display !== 'none' && rows.length > 0) {
                    const inputVal = input.value.trim().toLowerCase();

                    // If user explicitly navigated to a row using Arrow keys
                    if (activeRow && activeRow.dataset.barcode) {
                        e.preventDefault();
                        selectSuggestion(activeRow.dataset.barcode);
                        return;
                    }

                    // If a row in the dropdown matches the typed/scanned barcode exactly
                    const exactRow = rows.find(r => r.dataset.barcode && r.dataset.barcode.toLowerCase() === inputVal);
                    if (exactRow) {
                        e.preventDefault();
                        selectSuggestion(exactRow.dataset.barcode);
                        return;
                    }
                }
                closeDropdown();
            }
        });
    }

    initDropdown() {
        const toggle = document.getElementById('cartOptionsDropdown');
        const menu = document.querySelector('.cart-dropdown .dropdown-menu');
        if (!toggle || !menu) return;

        // Try Bootstrap first
        if (typeof bootstrap !== 'undefined') {
            new bootstrap.Dropdown(toggle);
            return;
        }

        // Fallback: manual dropdown toggle
        toggle.addEventListener('click', e => {
            e.preventDefault();
            e.stopPropagation();

            const isOpen = menu.classList.contains('show');

            // Close all other dropdowns
            document.querySelectorAll('.dropdown-menu.show').forEach(m => m.classList.remove('show'));

            // Toggle current dropdown
            if (!isOpen) {
                menu.classList.add('show');
            }
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', e => {
            if (!toggle.contains(e.target) && !menu.contains(e.target)) {
                menu.classList.remove('show');
            }
        });

        // Close dropdown when pressing Escape
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape') {
                menu.classList.remove('show');
            }
        });
    }
    /*** ───────── CAMERA BARCODE SCANNER ───────── ***/
    /**
     * Initialize camera-based barcode scanner for mobile devices.
     * Uses html5-qrcode library with Code 128 format support.
     * Only active on mobile (button visibility controlled by CSS).
     * @private
     */
    initBarcodeScanner() {
        const cameraScanBtn = document.getElementById('cameraScanBtn');
        const dialog = document.getElementById('barcodeScannerDialog');
        const closeBtn = document.getElementById('scannerCloseBtn');

        if (!cameraScanBtn || !dialog) return;

        // Only enable on actual mobile/touch devices (not just narrow desktop windows)
        const isTouchDevice = ('ontouchstart' in window)
            || (navigator.maxTouchPoints > 0)
            || window.matchMedia('(pointer: coarse)').matches;

        if (!isTouchDevice) {
            // Hide the button entirely on non-touch devices
            cameraScanBtn.style.display = 'none';
            return;
        }

        // Scanner instance reference
        this.html5QrCode = null;
        this.scannerIsOpen = false;

        // Open scanner on camera button click
        cameraScanBtn.addEventListener('click', () => this.openScanner());

        // Close scanner on close button click
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.closeScanner());
        }

        // Close scanner on Escape key or dialog cancel
        dialog.addEventListener('cancel', (e) => {
            e.preventDefault();
            this.closeScanner();
        });

        // Pre-build AudioContext for beep (must be created after user gesture)
        this.audioCtx = null;
    }

    /**
     * Open the camera scanner dialog and start scanning.
     * Uses rear camera (environment facing) for barcode scanning.
     */
    async openScanner() {
        const dialog = document.getElementById('barcodeScannerDialog');
        const statusEl = document.getElementById('scannerStatus');

        if (!dialog || this.scannerIsOpen) return;

        // Only allow camera scanner on mobile devices
        const isMobile = window.matchMedia('(max-width: 768px)').matches;
        if (!isMobile) return;

        // Check if html5-qrcode library is loaded
        if (typeof Html5Qrcode === 'undefined') {
            this.notify('Barcode scanner library not loaded', 'error');
            return;
        }

        // Check for secure context (HTTPS or localhost)
        if (!window.isSecureContext) {
            this.notify('Camera requires HTTPS. Please use a secure connection.', 'error');
            return;
        }

        // Initialize AudioContext on first user gesture
        if (!this.audioCtx) {
            try {
                this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            } catch (_) {
                // Audio not supported, scanning still works
            }
        }

        this.scannerIsOpen = true;
        dialog.showModal();

        if (statusEl) statusEl.textContent = 'Initializing camera...';

        // Small delay to let the dialog render and get dimensions
        await new Promise(resolve => setTimeout(resolve, 300));

        try {
            this.html5QrCode = new Html5Qrcode('scannerViewfinder', {
                verbose: false,
            });

            const config = {
                fps: 10,
                qrbox: { width: 250, height: 150 },
                formatsToSupport: [Html5QrcodeSupportedFormats.CODE_128],
                disableFlip: false,
            };

            // Race between camera start and a timeout
            const startPromise = this.html5QrCode.start(
                { facingMode: 'environment' },
                config,
                (decodedText) => this.onBarcodeScanSuccess(decodedText),
                () => { } // ignore scan failures (frames without barcode)
            );

            const timeoutPromise = new Promise((_, reject) =>
                setTimeout(() => reject(new Error('Camera timed out. Please check permissions and try again.')), 10000)
            );

            await Promise.race([startPromise, timeoutPromise]);

            if (statusEl) statusEl.textContent = 'Camera ready — point at barcode';
        } catch (err) {
            console.error('[CartManager] Scanner error:', err);

            let errorMsg = err.message || 'Could not start camera.';
            const errStr = err.toString();
            if (errStr.includes('NotAllowedError')) {
                errorMsg = 'Camera permission denied. Please allow camera access in your browser settings.';
            } else if (errStr.includes('NotFoundError')) {
                errorMsg = 'No camera found on this device.';
            } else if (errStr.includes('NotReadableError')) {
                errorMsg = 'Camera is in use by another app.';
            } else if (errStr.includes('OverconstrainedError')) {
                // Retry with any available camera
                try {
                    if (statusEl) statusEl.textContent = 'Trying alternate camera...';
                    await this.html5QrCode.start(
                        { facingMode: 'user' },
                        {
                            fps: 10,
                            qrbox: { width: 250, height: 150 },
                            formatsToSupport: [Html5QrcodeSupportedFormats.CODE_128],
                        },
                        (decodedText) => this.onBarcodeScanSuccess(decodedText),
                        () => { }
                    );
                    if (statusEl) statusEl.textContent = 'Camera ready — point at barcode';
                    return;
                } catch (retryErr) {
                    errorMsg = 'Could not access any camera.';
                }
            }

            if (statusEl) statusEl.textContent = errorMsg;
            this.notify(errorMsg, 'error');

            // Auto-close after showing error for 2 seconds
            setTimeout(() => this.closeScanner(), 2500);
        }
    }

    /**
     * Handle successful barcode scan from camera.
     * Plays beep, vibrates, closes scanner, and submits the barcode.
     * @param {string} decodedText - The decoded barcode string
     * @private
     */
    onBarcodeScanSuccess(decodedText) {
        if (!decodedText || !this.scannerIsOpen) return;

        // Prevent duplicate rapid scans
        this.scannerIsOpen = false;

        // Visual feedback: green flash
        const wrapper = document.querySelector('.scanner-viewfinder-wrapper');
        if (wrapper) {
            wrapper.classList.add('scan-success');
            setTimeout(() => wrapper.classList.remove('scan-success'), 500);
        }

        // Audio feedback: beep
        this.playBeep();

        // Haptic feedback: vibrate
        if (navigator.vibrate) {
            navigator.vibrate(100);
        }

        // Update status
        const statusEl = document.getElementById('scannerStatus');
        if (statusEl) statusEl.textContent = `Scanned: ${decodedText}`;

        // Close scanner after a brief moment to show feedback
        setTimeout(() => {
            this.closeScanner();

            // Fill barcode input and auto-submit
            if (this.dom.input) {
                this.dom.input.value = decodedText;
                // Trigger form submit
                if (this.dom.form) {
                    this.dom.form.requestSubmit();
                }
            }
        }, 400);
    }

    /**
     * Close the camera scanner dialog and stop the camera.
     * Dialog closes immediately; camera cleanup happens after.
     */
    async closeScanner() {
        const dialog = document.getElementById('barcodeScannerDialog');

        // Close dialog FIRST so UI unblocks immediately
        this.scannerIsOpen = false;
        if (dialog && dialog.open) {
            dialog.close();
        }

        // Then cleanup camera (non-blocking)
        try {
            if (this.html5QrCode) {
                try {
                    await this.html5QrCode.stop();
                } catch (_) {
                    // stop() can fail if camera never started — that's fine
                }
                try {
                    this.html5QrCode.clear();
                } catch (_) {
                    // clear() can fail on partially initialized scanner
                }
                this.html5QrCode = null;
            }
        } catch (err) {
            console.warn('[CartManager] Error cleaning up scanner:', err);
        }

        this.focusBarcode();
    }

    /**
     * Play a short beep sound using the Web Audio API.
     * No external sound file needed.
     * @private
     */
    playBeep() {
        if (!this.audioCtx) return;

        try {
            const oscillator = this.audioCtx.createOscillator();
            const gainNode = this.audioCtx.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(this.audioCtx.destination);

            oscillator.type = 'sine';
            oscillator.frequency.setValueAtTime(1200, this.audioCtx.currentTime);
            gainNode.gain.setValueAtTime(0.3, this.audioCtx.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.001, this.audioCtx.currentTime + 0.15);

            oscillator.start(this.audioCtx.currentTime);
            oscillator.stop(this.audioCtx.currentTime + 0.15);
        } catch (_) {
            // Audio playback not critical, silently ignore
        }
    }
}

// Initialize cart manager when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.cartManager = new CartManager();
});
