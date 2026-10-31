/**
 * Reusable Filter Drawer & Dual Range Slider Utility
 * Used across Billing System list and management views
 */
(function(window) {
    'use strict';

    // Format plain decimal numbers without currency symbols (Rule 7 compliant)
    function formatPlainDecimal(num, decimals = 2) {
        const val = parseFloat(num);
        if (isNaN(val)) return '0.00';
        return val.toLocaleString('en-IN', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        });
    }

    const registeredSliders = [];

    /**
     * Dual Range Slider Component
     */
    class DualRangeSlider {
        constructor(config) {
            this.config = Object.assign({
                minRange: null,
                maxRange: null,
                progress: null,
                minInput: null,
                maxInput: null,
                display: null,
                min: 0,
                max: 100,
                step: 1,
                gap: 0,
                format: 'decimal', // 'decimal', 'percent', 'integer', or function(min, max)
                unit: '',
                onChange: null
            }, config);

            this.minRangeEl = typeof this.config.minRange === 'string' ? document.querySelector(this.config.minRange) : this.config.minRange;
            this.maxRangeEl = typeof this.config.maxRange === 'string' ? document.querySelector(this.config.maxRange) : this.config.maxRange;
            this.progressEl = typeof this.config.progress === 'string' ? document.querySelector(this.config.progress) : this.config.progress;
            this.minInputEl = typeof this.config.minInput === 'string' ? document.querySelector(this.config.minInput) : this.config.minInput;
            this.maxInputEl = typeof this.config.maxInput === 'string' ? document.querySelector(this.config.maxInput) : this.config.maxInput;
            this.displayEl = typeof this.config.display === 'string' ? document.querySelector(this.config.display) : this.config.display;

            this.min = parseFloat(this.config.min) || 0;
            this.max = parseFloat(this.config.max) || 100;
            this.step = parseFloat(this.config.step) || 1;
            this.gap = parseFloat(this.config.gap) || 0;

            this.init();
            registeredSliders.push(this);
        }

        init() {
            if (!this.minRangeEl || !this.maxRangeEl) return;

            this.applyRangeAttributes();

            this.minRangeEl.addEventListener('input', () => {
                let minVal = parseFloat(this.minRangeEl.value);
                let maxVal = parseFloat(this.maxRangeEl.value);
                if (minVal > maxVal - this.gap) {
                    this.minRangeEl.value = maxVal - this.gap;
                }
                this.update(false);
            });

            this.maxRangeEl.addEventListener('input', () => {
                let minVal = parseFloat(this.minRangeEl.value);
                let maxVal = parseFloat(this.maxRangeEl.value);
                if (maxVal < minVal + this.gap) {
                    this.maxRangeEl.value = minVal + this.gap;
                }
                this.update(false);
            });

            if (this.minInputEl) {
                this.minInputEl.addEventListener('input', () => this.update(true));
            }
            if (this.maxInputEl) {
                this.maxInputEl.addEventListener('input', () => this.update(true));
            }

            this.update(true);
        }

        applyRangeAttributes() {
            if (this.minRangeEl) {
                this.minRangeEl.min = this.min;
                this.minRangeEl.max = this.max;
                this.minRangeEl.step = this.step;
            }
            if (this.maxRangeEl) {
                this.maxRangeEl.min = this.min;
                this.maxRangeEl.max = this.max;
                this.maxRangeEl.step = this.step;
            }
        }

        setRangeBounds({ min, max, step, gap, format, unit }) {
            if (min !== undefined) this.min = parseFloat(min);
            if (max !== undefined) this.max = parseFloat(max);
            if (step !== undefined) this.step = parseFloat(step);
            if (gap !== undefined) this.gap = parseFloat(gap);
            if (format !== undefined) this.config.format = format;
            if (unit !== undefined) this.config.unit = unit;

            this.applyRangeAttributes();
            this.update(true);
        }

        update(fromInput = false) {
            if (!this.minRangeEl || !this.maxRangeEl) return;

            let minVal = parseFloat(fromInput ? (this.minInputEl ? this.minInputEl.value : this.min) : this.minRangeEl.value);
            let maxVal = parseFloat(fromInput ? (this.maxInputEl ? this.maxInputEl.value : this.max) : this.maxRangeEl.value);

            if (isNaN(minVal)) minVal = this.min;
            if (isNaN(maxVal)) maxVal = this.max;

            minVal = Math.max(this.min, Math.min(this.max, minVal));
            maxVal = Math.max(this.min, Math.min(this.max, maxVal));

            if (minVal > maxVal - this.gap) {
                if (fromInput) minVal = maxVal - this.gap;
                else {
                    minVal = maxVal - this.gap;
                    this.minRangeEl.value = minVal;
                }
            }

            if (!fromInput) {
                if (this.minInputEl) {
                    this.minInputEl.value = minVal > this.min ? (this.config.format === 'integer' ? Math.round(minVal) : minVal.toFixed(2)) : '';
                }
                if (this.maxInputEl) {
                    this.maxInputEl.value = maxVal < this.max ? (this.config.format === 'integer' ? Math.round(maxVal) : maxVal.toFixed(2)) : '';
                }
            } else {
                this.minRangeEl.value = minVal;
                this.maxRangeEl.value = maxVal;
            }

            // Update visual progress track
            if (this.progressEl) {
                const span = this.max - this.min;
                const leftPercent = span > 0 ? Math.max(0, Math.min(100, ((minVal - this.min) / span) * 100)) : 0;
                const rightPercent = span > 0 ? Math.max(0, Math.min(100, 100 - ((maxVal - this.min) / span) * 100)) : 0;
                this.progressEl.style.left = leftPercent + '%';
                this.progressEl.style.right = rightPercent + '%';
            }

            // Update display badge
            if (this.displayEl) {
                if (typeof this.config.format === 'function') {
                    this.displayEl.textContent = this.config.format(minVal, maxVal);
                } else if (this.config.format === 'percent') {
                    this.displayEl.textContent = `${Math.round(minVal)}% - ${Math.round(maxVal)}%`;
                } else if (this.config.format === 'integer') {
                    this.displayEl.textContent = `${Math.round(minVal)} - ${Math.round(maxVal)}`;
                } else {
                    // Default plain decimal
                    this.displayEl.textContent = `${formatPlainDecimal(minVal)} - ${formatPlainDecimal(maxVal)}`;
                }
            }

            if (typeof this.config.onChange === 'function') {
                this.config.onChange(minVal, maxVal);
            }
        }

        reset() {
            if (this.minInputEl) this.minInputEl.value = '';
            if (this.maxInputEl) this.maxInputEl.value = '';
            if (this.minRangeEl) this.minRangeEl.value = this.min;
            if (this.maxRangeEl) this.maxRangeEl.value = this.max;
            this.update(false);
        }

        getValues() {
            return {
                min: parseFloat(this.minRangeEl ? this.minRangeEl.value : this.min),
                max: parseFloat(this.maxRangeEl ? this.maxRangeEl.value : this.max)
            };
        }
    }

    /**
     * Helper to initialize a dual range slider
     */
    function initDualRangeSlider(config) {
        return new DualRangeSlider(config);
    }

    /**
     * Segmented Control binder
     */
    function initSegmentedControl(containerSelector, onChange) {
        const container = typeof containerSelector === 'string' ? document.querySelector(containerSelector) : containerSelector;
        if (!container) return;

        const options = container.querySelectorAll('.segmented-control-option');
        options.forEach(option => {
            option.addEventListener('click', function() {
                options.forEach(opt => opt.classList.remove('active'));
                this.classList.add('active');
                const radio = this.querySelector('input[type="radio"]');
                if (radio) {
                    radio.checked = true;
                    if (typeof onChange === 'function') {
                        onChange(radio.value, radio);
                    }
                }
            });
        });
    }

    /**
     * Date calculation helpers for quick presets
     */
    function formatDateISO(d) {
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }

    function getDatePresetRange(presetName) {
        const now = new Date();
        const todayStr = formatDateISO(now);

        switch (presetName) {
            case 'today':
                return { from: todayStr, to: todayStr };
            case 'yesterday': {
                const yest = new Date(now);
                yest.setDate(now.getDate() - 1);
                const yStr = formatDateISO(yest);
                return { from: yStr, to: yStr };
            }
            case 'this_week': {
                const day = now.getDay();
                const diff = now.getDate() - day + (day === 0 ? -6 : 1); // Monday
                const monday = new Date(now);
                monday.setDate(diff);
                return { from: formatDateISO(monday), to: todayStr };
            }
            case 'this_month': {
                const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
                return { from: formatDateISO(firstDay), to: todayStr };
            }
            case 'last_month': {
                const firstDayPrev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
                const lastDayPrev = new Date(now.getFullYear(), now.getMonth(), 0);
                return { from: formatDateISO(firstDayPrev), to: formatDateISO(lastDayPrev) };
            }
            case 'this_fy': {
                const month = now.getMonth(); // 0-based, April is 3
                const startYear = month >= 3 ? now.getFullYear() : now.getFullYear() - 1;
                const endYear = startYear + 1;
                return { from: `${startYear}-04-01`, to: `${endYear}-03-31` };
            }
            default:
                return null;
        }
    }

    /**
     * Declarative Filter Drawer Controller
     * Handles active filter tracking, funnel badges, hover previews, URL deep linking, and resets
     */
    function initFilterDrawer(userOptions) {
        const options = Object.assign({
            drawerId: 'filterDrawer',
            formId: 'searchForm',
            tableId: 'data_table',
            badgeId: 'activeFilterBadge',
            funnelBtnId: 'openFilterDrawerBtn',
            funnelWrapperId: 'filterFunnelWrapper',
            hoverListId: 'filterHoverList',
            hoverCountId: 'filterHoverCount',
            hoverClearAllId: 'filterHoverClearAll',
            applyBtnId: 'applyModalFiltersBtn',
            resetBtnId: 'resetModalFiltersBtn',
            showChips: false,
            chipsContainerId: null,
            syncUrl: true,
            filters: []
        }, userOptions);

        const drawerEl = document.getElementById(options.drawerId);
        const formEl = document.getElementById(options.formId);
        const tableEl = document.getElementById(options.tableId);
        const badgeEl = document.getElementById(options.badgeId);
        const funnelBtn = document.getElementById(options.funnelBtnId);
        const funnelWrapper = document.getElementById(options.funnelWrapperId);
        const hoverList = document.getElementById(options.hoverListId);
        const hoverCount = document.getElementById(options.hoverCountId);
        const hoverClearAll = document.getElementById(options.hoverClearAllId);
        const chipsContainer = document.getElementById(options.chipsContainerId);
        const hoverPreview = document.getElementById(options.hoverPreviewId || 'filterHoverPreview') || (funnelWrapper ? funnelWrapper.querySelector('.filter-hover-preview') : null);

        function dismissHoverPreview() {
            if (funnelWrapper) {
                funnelWrapper.classList.remove('show-hover-preview');
            }
            if (hoverPreview) {
                hoverPreview.style.display = 'none';
                setTimeout(() => {
                    hoverPreview.style.removeProperty('display');
                }, 100);
            }
            if (funnelWrapper && funnelWrapper.contains(document.activeElement) && typeof document.activeElement.blur === 'function') {
                document.activeElement.blur();
            }
        }

        function getEl(target) {
            if (!target) return null;
            if (typeof target === 'string') {
                return target.startsWith('#') || target.startsWith('.') ? document.querySelector(target) : document.getElementById(target);
            }
            return target;
        }

        // Wire sliders to updateUI automatically
        options.filters.forEach(item => {
            if (item.type === 'slider' && item.slider) {
                const origOnChange = item.slider.config.onChange;
                item.slider.config.onChange = function(min, max) {
                    if (typeof origOnChange === 'function') origOnChange(min, max);
                    updateUI();
                };
            }
        });

        // 1. Evaluate Active Filters
        function getActiveFilters() {
            const activeList = [];
            options.filters.forEach(item => {
                if (item.type === 'slider' && item.slider) {
                    const minVal = item.slider.minInputEl ? item.slider.minInputEl.value.trim() : '';
                    const maxVal = item.slider.maxInputEl ? item.slider.maxInputEl.value.trim() : '';
                    if (minVal !== '' || maxVal !== '') {
                        let text = '';
                        const fmt = typeof item.format === 'function' ? item.format : (item.format === 'integer' ? (v => Math.round(v)) : (item.format === 'percent' ? (v => `${Math.round(v)}%`) : formatPlainDecimal));
                        if (minVal !== '' && maxVal !== '') {
                            text = `${fmt(minVal)} - ${fmt(maxVal)}`;
                        } else if (minVal !== '') {
                            text = `≥ ${fmt(minVal)}`;
                        } else {
                            text = `≤ ${fmt(maxVal)}`;
                        }
                        activeList.push({
                            key: item.key || 'slider',
                            label: item.label || 'Range',
                            value: text,
                            rawItem: item
                        });
                    }
                } else if (item.type === 'daterange') {
                    const fromEl = getEl(item.fromId || item.fromInput);
                    const toEl = getEl(item.toId || item.toInput);
                    const dFrom = fromEl ? fromEl.value : '';
                    const dTo = toEl ? toEl.value : '';
                    if (dFrom || dTo) {
                        const text = (dFrom && dTo) ? `${dFrom} to ${dTo}` : (dFrom ? `From ${dFrom}` : `Up to ${dTo}`);
                        activeList.push({
                            key: item.key || 'daterange',
                            label: item.label || 'Date',
                            value: text,
                            rawItem: item
                        });
                    }
                } else if (item.type === 'checkbox') {
                    const el = getEl(item.id || item.input);
                    if (el && el.checked) {
                        activeList.push({
                            key: item.key || el.name || el.id,
                            label: item.label || 'Filter',
                            value: item.text || el.getAttribute('data-active-text') || 'Active',
                            rawItem: item
                        });
                    }
                } else if (item.type === 'select') {
                    const el = getEl(item.id || item.input);
                    if (el && el.value && el.value !== (item.defaultValue || '')) {
                        const text = el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : el.value;
                        activeList.push({
                            key: item.key || el.name || el.id,
                            label: item.label || el.name,
                            value: text,
                            rawItem: item
                        });
                    }
                } else if (item.type === 'radio') {
                    const selector = item.name ? `input[name="${item.name}"]:checked` : null;
                    const checkedRadio = selector && formEl ? formEl.querySelector(selector) : null;
                    if (checkedRadio && checkedRadio.value !== (item.defaultValue || '')) {
                        const labelText = checkedRadio.getAttribute('data-label') || checkedRadio.value;
                        activeList.push({
                            key: item.key || item.name,
                            label: item.label || item.name,
                            value: labelText,
                            rawItem: item
                        });
                    }
                } else {
                    const el = getEl(item.id || item.input);
                    if (el && el.value && el.value.trim() !== '' && el.value !== (item.defaultValue || '')) {
                        activeList.push({
                            key: item.key || el.name || el.id,
                            label: item.label || el.name,
                            value: el.value.trim(),
                            rawItem: item
                        });
                    }
                }
            });
            return activeList;
        }

        // 2. Clear single filter
        function clearFilter(filterKey) {
            const match = options.filters.find(f => (f.key === filterKey || (f.id && f.id === filterKey) || (f.input && (f.input === filterKey || f.input === '#' + filterKey))));
            if (!match) return;

            if (match.type === 'slider' && match.slider) {
                match.slider.reset();
            } else if (match.type === 'daterange') {
                const fromEl = getEl(match.fromId || match.fromInput);
                const toEl = getEl(match.toId || match.toInput);
                if (fromEl) fromEl.value = '';
                if (toEl) toEl.value = '';
                if (drawerEl) {
                    drawerEl.querySelectorAll('.date-preset-btn').forEach(b => b.classList.remove('active'));
                }
            } else if (match.type === 'checkbox') {
                const el = getEl(match.id || match.input);
                if (el) el.checked = false;
            } else if (match.type === 'radio') {
                if (formEl) {
                    const defRadio = formEl.querySelector(`input[name="${match.name}"][value="${match.defaultValue || ''}"]`);
                    if (defRadio) {
                        defRadio.checked = true;
                        const seg = defRadio.closest('.segmented-control-option');
                        if (seg && seg.parentElement) {
                            seg.parentElement.querySelectorAll('.segmented-control-option').forEach(o => o.classList.remove('active'));
                            seg.classList.add('active');
                        }
                    }
                }
            } else {
                const el = getEl(match.id || match.input);
                if (el) el.value = match.defaultValue !== undefined ? match.defaultValue : '';
            }
        }

        // 3. Clear all filters
        function clearAll() {
            options.filters.forEach(item => clearFilter(item.key));
            if (drawerEl) {
                drawerEl.querySelectorAll('.date-preset-btn').forEach(b => b.classList.remove('active'));
            }
            updateUI();
            if (typeof reloadTable === 'function') {
                reloadTable(options.tableId);
            }
        }

        // 4. Update UI (badge, hover list, chips bar, sync URL)
        function updateUI() {
            const activeFilters = getActiveFilters();
            const count = activeFilters.length;

            // Funnel badge
            if (badgeEl) {
                badgeEl.textContent = count;
                if (count > 0) {
                    badgeEl.classList.remove('d-none');
                    if (funnelBtn) funnelBtn.classList.add('has-active');
                    if (funnelWrapper) funnelWrapper.classList.add('show-hover-preview');
                } else {
                    badgeEl.classList.add('d-none');
                    if (funnelBtn) funnelBtn.classList.remove('has-active');
                    if (funnelWrapper) funnelWrapper.classList.remove('show-hover-preview');
                }
            }

            // Hover count & list
            if (hoverCount) hoverCount.textContent = count;
            if (hoverList) {
                if (count > 0) {
                    hoverList.innerHTML = activeFilters.map(item => `
                        <div class="filter-hover-item">
                            <div class="filter-hover-item-content">
                                <span class="filter-hover-item-label">${item.label}:</span>
                                <span class="filter-hover-item-value" title="${item.value}">${item.value}</span>
                            </div>
                            <span class="filter-hover-item-remove" data-clear="${item.key}" role="button" title="Remove ${item.label} filter">&times;</span>
                        </div>
                    `).join('');
                } else {
                    hoverList.innerHTML = '<div class="text-muted text-center py-2 small">No active filters</div>';
                }
            }

            // Touch / Mobile chips container (if element exists and enabled)
            if (chipsContainer) {
                if (options.showChips && count > 0) {
                    chipsContainer.classList.remove('d-none');
                    chipsContainer.innerHTML = activeFilters.map(item => `
                        <div class="active-filter-chip">
                            <span class="active-filter-chip-label">${item.label}:</span>
                            <span class="active-filter-chip-value">${item.value}</span>
                            <span class="active-filter-chip-remove" data-clear="${item.key}" role="button" title="Remove filter">&times;</span>
                        </div>
                    `).join('') + `
                        <button type="button" class="btn btn-link btn-sm p-0 text-danger text-decoration-none ms-1 filter-chips-clear-all" style="font-size:0.75rem;">
                            Clear All
                        </button>
                    `;
                } else {
                    chipsContainer.classList.add('d-none');
                    chipsContainer.innerHTML = '';
                }
            }

            // Sync URL State
            if (options.syncUrl && formEl) {
                syncUrlParams(formEl, options);
            }
        }

        // 5. URL Sync Helper
        function syncUrlParams(form, opts) {
            try {
                const formData = new FormData(form);
                const params = new URLSearchParams();

                // Preserve search
                const searchInput = form.querySelector('input[type="search"]');
                if (searchInput && searchInput.value.trim()) {
                    params.set('search', searchInput.value.trim());
                }

                // Preserve sort
                if (tableEl && tableEl.dataset.sort) {
                    params.set('sort', tableEl.dataset.sort);
                }

                for (const [key, value] of formData.entries()) {
                    if (value && String(value).trim() !== '' && key !== 'search') {
                        params.set(key, String(value).trim());
                    }
                }

                const newQuery = params.toString();
                const newUrl = window.location.pathname + (newQuery ? '?' + newQuery : '');
                window.history.replaceState({ filterState: true }, '', newUrl);
            } catch (e) {
                // Ignore history replaceState error if blocked
            }
        }

        // 6. Hydrate From URL on load
        function hydrateFromUrl() {
            if (!options.syncUrl || !formEl) return false;
            try {
                const urlParams = new URLSearchParams(window.location.search);
                if ([...urlParams.keys()].length === 0) return false;

                let hydrated = false;

                const searchInput = formEl.querySelector('input[type="search"]');
                if (searchInput && urlParams.has('search')) {
                    searchInput.value = urlParams.get('search');
                    hydrated = true;
                }

                options.filters.forEach(item => {
                    if (item.type === 'slider' && item.slider) {
                        const minKey = item.minKey || (item.slider.minInputEl ? item.slider.minInputEl.name : 'min_amount');
                        const maxKey = item.maxKey || (item.slider.maxInputEl ? item.slider.maxInputEl.name : 'max_amount');
                        const minVal = urlParams.get(minKey);
                        const maxVal = urlParams.get(maxKey);
                        if (minVal !== null || maxVal !== null) {
                            if (minVal !== null && item.slider.minInputEl) item.slider.minInputEl.value = minVal;
                            if (maxVal !== null && item.slider.maxInputEl) item.slider.maxInputEl.value = maxVal;
                            item.slider.update(true);
                            hydrated = true;
                        }
                    } else if (item.type === 'daterange') {
                        const fromEl = getEl(item.fromId || item.fromInput);
                        const toEl = getEl(item.toId || item.toInput);
                        const fromKey = fromEl ? fromEl.name : 'date_from';
                        const toKey = toEl ? toEl.name : 'date_to';
                        if (fromEl && urlParams.has(fromKey)) {
                            fromEl.value = urlParams.get(fromKey);
                            hydrated = true;
                        }
                        if (toEl && urlParams.has(toKey)) {
                            toEl.value = urlParams.get(toKey);
                            hydrated = true;
                        }
                    } else if (item.type === 'checkbox') {
                        const el = getEl(item.id || item.input);
                        if (el && urlParams.has(el.name)) {
                            const val = urlParams.get(el.name);
                            el.checked = val === '1' || val === 'true' || val === 'yes' || val === el.value;
                            hydrated = true;
                        }
                    } else if (item.type === 'radio') {
                        if (item.name && urlParams.has(item.name)) {
                            const val = urlParams.get(item.name);
                            const radio = formEl.querySelector(`input[name="${item.name}"][value="${val}"]`);
                            if (radio) {
                                radio.checked = true;
                                const seg = radio.closest('.segmented-control-option');
                                if (seg && seg.parentElement) {
                                    seg.parentElement.querySelectorAll('.segmented-control-option').forEach(o => o.classList.remove('active'));
                                    seg.classList.add('active');
                                }
                                hydrated = true;
                            }
                        }
                    } else {
                        const el = getEl(item.id || item.input);
                        if (el && urlParams.has(el.name)) {
                            el.value = urlParams.get(el.name);
                            hydrated = true;
                        }
                    }
                });

                return hydrated;
            } catch (e) {
                return false;
            }
        }

        // 7. Event Bindings
        // Apply button inside offcanvas drawer
        const applyBtn = document.getElementById(options.applyBtnId) || (drawerEl ? drawerEl.querySelector('#applyDrawerFiltersBtn, #applyModalFiltersBtn') : null);
        if (applyBtn) {
            applyBtn.addEventListener('click', function() {
                if (typeof bootstrap !== 'undefined' && drawerEl) {
                    const drawerInst = bootstrap.Offcanvas.getInstance(drawerEl) || bootstrap.Offcanvas.getOrCreateInstance(drawerEl);
                    if (drawerInst) drawerInst.hide();
                }
                updateUI();
                if (typeof reloadTable === 'function') {
                    reloadTable(options.tableId);
                }
            });
        }

        // Reset button inside offcanvas drawer
        const resetBtn = document.getElementById(options.resetBtnId) || (drawerEl ? drawerEl.querySelector('#resetDrawerFiltersBtn, #resetModalFiltersBtn, #clearAllFiltersBtn') : null);
        if (resetBtn) {
            resetBtn.addEventListener('click', function() {
                clearAll();
                if (typeof bootstrap !== 'undefined' && drawerEl) {
                    const drawerInst = bootstrap.Offcanvas.getInstance(drawerEl) || bootstrap.Offcanvas.getOrCreateInstance(drawerEl);
                    if (drawerInst) drawerInst.hide();
                }
            });
        }

        // Funnel button click
        if (funnelBtn) {
            funnelBtn.addEventListener('click', function() {
                dismissHoverPreview();
            });
        }

        // Offcanvas drawer show event
        if (drawerEl) {
            drawerEl.addEventListener('show.bs.offcanvas', dismissHoverPreview);
        }

        // Hover clear all
        if (hoverClearAll) {
            hoverClearAll.addEventListener('click', function() {
                clearAll();
                dismissHoverPreview();
            });
        }

        // Hover list item remove [data-clear]
        if (hoverList) {
            hoverList.addEventListener('click', function(e) {
                const removeBtn = e.target.closest('.filter-hover-item-remove');
                if (!removeBtn) return;
                const clearKey = removeBtn.getAttribute('data-clear');
                if (clearKey) {
                    clearFilter(clearKey);
                    updateUI();
                    if (typeof reloadTable === 'function') {
                        reloadTable(options.tableId);
                    }
                    dismissHoverPreview();
                }
            });
        }

        // Outside click or touch to dismiss hover preview
        document.addEventListener('click', function(e) {
            if (funnelWrapper && !funnelWrapper.contains(e.target)) {
                dismissHoverPreview();
            }
        });
        document.addEventListener('touchstart', function(e) {
            if (funnelWrapper && !funnelWrapper.contains(e.target)) {
                dismissHoverPreview();
            }
        }, { passive: true });

        // Touch chips container delegated clicks
        if (chipsContainer) {
            chipsContainer.addEventListener('click', function(e) {
                const removeBtn = e.target.closest('.active-filter-chip-remove');
                if (removeBtn) {
                    const clearKey = removeBtn.getAttribute('data-clear');
                    if (clearKey) {
                        clearFilter(clearKey);
                        updateUI();
                        if (typeof reloadTable === 'function') {
                            reloadTable(options.tableId);
                        }
                    }
                    return;
                }
                if (e.target.closest('.filter-chips-clear-all')) {
                    clearAll();
                }
            });
        }

        // Form change & input sync
        if (formEl) {
            formEl.addEventListener('change', updateUI);
            formEl.addEventListener('input', function(e) {
                if (e.target && e.target.type === 'search') return;
                updateUI();
            });
            formEl.addEventListener('submit', updateUI);
        }

        // Table reloaded event
        if (tableEl) {
            tableEl.addEventListener('tableDataLoaded', updateUI);
        }

        // Date Preset buttons inside drawer
        if (drawerEl) {
            drawerEl.addEventListener('click', function(e) {
                const presetBtn = e.target.closest('.date-preset-btn');
                if (!presetBtn) return;

                const preset = presetBtn.getAttribute('data-preset');
                const fromTarget = presetBtn.getAttribute('data-from') || '#dateFromFilter';
                const toTarget = presetBtn.getAttribute('data-to') || '#dateToFilter';
                const fromEl = getEl(fromTarget);
                const toEl = getEl(toTarget);

                if (fromEl && toEl && preset) {
                    const range = getDatePresetRange(preset);
                    if (range) {
                        fromEl.value = range.from;
                        toEl.value = range.to;
                        const parent = presetBtn.parentElement;
                        if (parent) {
                            parent.querySelectorAll('.date-preset-btn').forEach(b => b.classList.remove('active'));
                        }
                        presetBtn.classList.add('active');
                        updateUI();
                    }
                }
            });
        }

        // Initialize state
        const hadUrlParams = hydrateFromUrl();
        updateUI();

        return {
            updateUI,
            clearAll,
            clearFilter,
            getActiveFilters,
            hadUrlParams
        };
    }

    // Auto-update slider progress positions whenever an offcanvas drawer is opened
    document.addEventListener('DOMContentLoaded', function() {
        document.querySelectorAll('.offcanvas').forEach(offcanvasEl => {
            offcanvasEl.addEventListener('shown.bs.offcanvas', function() {
                registeredSliders.forEach(slider => {
                    if (offcanvasEl.contains(slider.minRangeEl)) {
                        slider.update(true);
                    }
                });
            });
        });
    });

    // Expose to window
    window.formatPlainDecimal = formatPlainDecimal;
    window.DualRangeSlider = DualRangeSlider;
    window.initDualRangeSlider = initDualRangeSlider;
    window.initSegmentedControl = initSegmentedControl;
    window.initFilterDrawer = initFilterDrawer;
    window.getDatePresetRange = getDatePresetRange;

})(window);
