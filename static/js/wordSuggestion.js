/**
 * WordSuggestion - Flexible Autocomplete / Spell Suggestion System
 *
 * WHY THIS DESIGN?
 * ----------------
 * - Debouncing: avoids firing too many network requests on fast typing.
 * - AbortController: cancels stale fetches so only the latest query counts.
 * - Accessibility (ARIA): adds roles, aria-controls, aria-autocomplete for screen readers.
 * - Event-driven: supports both callback & custom events for integration flexibility.
 * - Cleanup: destroy() removes listeners, aborts fetches → prevents memory leaks.
 * - Safe keyboard navigation: handles Enter, Tab, Esc, Arrows gracefully.
 * - Configurable: accepts options for min length, debounce delay, etc.
 *
 * NOTE: Instead of relying on jQuery-style plugins (`$('#id')...`), this class is vanilla JS.
 * Use `initWordSuggestion(inputElement, url, options)` to initialize.
 */

class WordSuggestion {
    constructor(inputElement, suggestionUrl, options = {}) {
        this.input = inputElement;
        this.options = {
            debounceDelay: 180,
            minQueryLength: 2,
            maxSuggestions: 5,
            url: suggestionUrl || "",
            onSuggestionSelected: null, // optional callback
            allowSpaces: true, // configurable space handling (allow spaces for full multi-word query autocomplete)
            multiWord: false, // default false for search engine style full query replacement
            ...options
        };

        this.suggestions = [];
        this.selectedIndex = -1;
        this.debounceTimer = null;
        this.dropdown = null;
        this.abortController = null;
        this.currentQuery = "";
        this.isSelecting = false;
        this.queryCache = new Map();
        this.maxQueryCache = 50;

        // Bind methods to instance
        this.boundHandleInput = (e) => this.handleInput(e);
        this.boundHandleKeydown = (e) => this.handleKeydown(e);
        this.boundHandleFocus = () => this.handleFocus();
        this.boundHandleBlur = (e) => this.handleBlur(e);
        this.boundHandleOutsideAction = (e) => this.handleOutsideAction(e);

        this.init();
    }

    // ----------- INIT -----------
    init() {
        // Store focus state before initialization
        const hadFocus = document.activeElement === this.input;

        this.createDropdown();
        this.bindEvents();

        // Restore focus if input had it before
        if (hadFocus) {
            this.input.focus();
        }
    }

    createDropdown() {
        this.dropdown = document.createElement('div');
        this.dropdown.className = 'word-suggestion-dropdown';
        this.dropdown.setAttribute('role', 'listbox');
        this.dropdown.setAttribute('aria-live', 'polite');
        this.dropdown.setAttribute('aria-hidden', 'true');
        this.dropdown.id = `dropdown-${Math.random().toString(36).substr(2, 9)}`;

        this.input.setAttribute('aria-autocomplete', 'list');
        this.input.setAttribute('aria-controls', this.dropdown.id);

        // Prevent input from losing focus when clicking inside dropdown
        this.dropdown.addEventListener('mousedown', (e) => {
            e.preventDefault();
        });

        // Find the best container for the dropdown
        const searchExpanded = this.input.closest('.search-expanded');
        if (searchExpanded) {
            this.container = searchExpanded;
            searchExpanded.appendChild(this.dropdown);
        } else if (this.input.parentElement && this.input.parentElement.classList.contains('word-suggestion-container')) {
            this.container = this.input.parentElement;
            this.container.appendChild(this.dropdown);
        } else {
            // Wrap input in .word-suggestion-container so dropdown anchors directly below the input
            const wrapper = document.createElement('div');
            wrapper.className = 'word-suggestion-container';
            this.input.parentNode.insertBefore(wrapper, this.input);
            wrapper.appendChild(this.input);
            wrapper.appendChild(this.dropdown);
            this.wrapper = wrapper;
            this.container = wrapper;
        }

        // Set position relative on container to ensure dropdown is positioned correctly
        if (this.container) {
            const computedStyle = window.getComputedStyle(this.container);
            if (computedStyle.position === 'static') {
                this.container.style.position = 'relative';
            }
        }
    }

    bindEvents() {
        this.input.addEventListener('input', this.boundHandleInput);
        this.input.addEventListener('keydown', this.boundHandleKeydown);
        this.input.addEventListener('focus', this.boundHandleFocus);
        this.input.addEventListener('blur', this.boundHandleBlur);
    }

    // ----------- HANDLERS -----------

    handleInput(e) {
        if (this.isSelecting) {
            return;
        }

        const rawValue = e.target.value;
        let query = rawValue.trim();

        if (this.options.multiWord) {
            query = this.getLastWord(rawValue);
        }

        clearTimeout(this.debounceTimer);

        if (query.length < this.options.minQueryLength) {
            this.suggestions = [];
            this.selectedIndex = -1;
            this.hideDropdown();
            return;
        }

        if (!this.options.allowSpaces && !this.options.multiWord && query.includes(' ')) {
            this.suggestions = [];
            this.selectedIndex = -1;
            this.hideDropdown();
            return;
        }

        this.debounceTimer = setTimeout(() => {
            if (document.activeElement === this.input) {
                this.searchSuggestions(query);
            }
        }, this.options.debounceDelay);
    }

    handleKeydown(e) {
        if (!this.dropdown.classList.contains('show'))
            return;

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.navigateDown();
                break;
            case 'ArrowUp':
                e.preventDefault();
                this.navigateUp();
                break;
            case 'Enter':
                if (this.selectedIndex >= 0) {
                    e.preventDefault();
                    this.selectSuggestion();
                } else {
                    this.hideDropdown();
                }
                break;
            case 'Tab': // Tab also accepts suggestion if highlighted, otherwise closes dropdown
                if (this.selectedIndex >= 0) {
                    e.preventDefault();
                    this.selectSuggestion();
                } else {
                    this.hideDropdown();
                }
                break;
            case 'Escape':
                e.preventDefault();
                this.hideDropdown();
                break;
        }
    }

    handleFocus() {
        if (this.isSelecting) {
            return;
        }
        const query = this.input.value.trim();
        if (query.length >= this.options.minQueryLength && this.suggestions.length > 0) {
            this.showDropdown();
        }
    }

    handleBlur(e) {
        clearTimeout(this.debounceTimer);
        setTimeout(() => {
            if (document.activeElement !== this.input && !this.dropdown.contains(document.activeElement)) {
                this.hideDropdown();
            }
        }, 150);
    }

    handleOutsideAction(e) {
        if (!this.input.contains(e.target) && !this.dropdown.contains(e.target)) {
            this.hideDropdown();
        }
    }

    // ----------- WORD EXTRACTION HELPERS -----------

    getLastWord(value) {
        const words = value.split(/\s+/);
        return words[words.length - 1] || '';
    }

    replaceLastWord(value, replacement) {
        const words = value.split(/\s+/);
        words[words.length - 1] = replacement;
        return words.join(' ');
    }

    // ----------- DATA FETCHING -----------

    async searchSuggestions(query) {
        if (document.activeElement !== this.input) {
            return;
        }

        const cacheKey = (query || "").trim().toLowerCase();
        if (this.queryCache && this.queryCache.has(cacheKey)) {
            this.suggestions = this.queryCache.get(cacheKey);
            this.selectedIndex = -1;
            if (this.suggestions.length > 0) {
                this.renderSuggestions();
                this.showDropdown();
            } else {
                this.hideDropdown();
            }
            return;
        }

        if (this.abortController)
            this.abortController.abort();

        this.abortController = new AbortController();
        this.currentQuery = query;

        try {
            const response = await fetch(`${this.options.url}?q=${encodeURIComponent(query)}`, { signal: this.abortController.signal });

            if (!response.ok)
                throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            const items = data.data || [];

            // Cache successful result
            if (this.queryCache) {
                if (this.queryCache.size >= this.maxQueryCache) {
                    const oldestKey = this.queryCache.keys().next().value;
                    this.queryCache.delete(oldestKey);
                }
                this.queryCache.set(cacheKey, items);
            }

            // Verify input is still focused before showing dropdown
            if (document.activeElement !== this.input) {
                this.suggestions = items;
                return;
            }

            this.suggestions = items;
            this.selectedIndex = -1;

            if (this.suggestions.length > 0) {
                this.renderSuggestions();
                this.showDropdown();
            } else {
                this.hideDropdown();
            }
        } catch (error) {
            if (error.name !== 'AbortError') {
                console.error('Error fetching suggestions:', error);
                this.hideDropdown();
            }
        }
    }

    // ----------- RENDER -----------

    renderSuggestions() {
        const fragment = document.createDocumentFragment();
        this.suggestions.forEach((suggestion, index) => {
            const item = this.createSuggestionItem(suggestion, index);
            fragment.appendChild(item);
        });
        this.dropdown.replaceChildren(fragment);
    }

    createSuggestionItem(suggestion, index) {
        const item = document.createElement('div');
        item.className = 'word-suggestion-item';
        item.dataset.index = index;
        item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', index === this.selectedIndex);

        const isObject = typeof suggestion === 'object' && suggestion !== null;
        const label = isObject ? (suggestion.label || '') : String(suggestion);
        const type = isObject ? (suggestion.type || '') : '';

        const contentSpan = document.createElement('span');
        contentSpan.className = 'suggestion-content';

        const query = (this.currentQuery || this.input.value).trim();
        const queryLower = query.toLowerCase();
        const labelLower = label.toLowerCase();

        const queryWords = queryLower.split(/\s+/).filter(Boolean);

        if (queryLower && labelLower.startsWith(queryLower)) {
            // Google-style Prefix Match: typed query in matched span, completion in bold
            const matchedText = label.slice(0, query.length);
            const completionText = label.slice(query.length);

            const matchedSpan = document.createElement('span');
            matchedSpan.className = 'suggestion-matched';
            matchedSpan.textContent = matchedText;

            const completionSpan = document.createElement('strong');
            completionSpan.className = 'suggestion-completion';
            completionSpan.textContent = completionText;

            contentSpan.appendChild(matchedSpan);
            contentSpan.appendChild(completionSpan);
        } else if (queryLower && labelLower.includes(queryLower)) {
            // Substring Match
            const idx = labelLower.indexOf(queryLower);
            const beforeText = label.slice(0, idx);
            const matchedText = label.slice(idx, idx + query.length);
            const afterText = label.slice(idx + query.length);

            if (beforeText) {
                const beforeSpan = document.createElement('strong');
                beforeSpan.className = 'suggestion-completion';
                beforeSpan.textContent = beforeText;
                contentSpan.appendChild(beforeSpan);
            }

            const matchedSpan = document.createElement('span');
            matchedSpan.className = 'suggestion-matched';
            matchedSpan.textContent = matchedText;
            contentSpan.appendChild(matchedSpan);

            if (afterText) {
                const afterSpan = document.createElement('strong');
                afterSpan.className = 'suggestion-completion';
                afterSpan.textContent = afterText;
                contentSpan.appendChild(afterSpan);
            }
        } else if (queryWords.length > 1 && queryWords.some(w => labelLower.includes(w))) {
            // Unordered Multi-Word Token Match (e.g. "gold special" matching "special gold")
            const labelTokens = label.split(/(\s+)/);
            labelTokens.forEach(token => {
                const tokenClean = token.toLowerCase();
                const matchedQWord = queryWords.find(qw => tokenClean.startsWith(qw));
                if (matchedQWord) {
                    const matchedPart = token.slice(0, matchedQWord.length);
                    const remPart = token.slice(matchedQWord.length);
                    const mSpan = document.createElement('span');
                    mSpan.className = 'suggestion-matched';
                    mSpan.textContent = matchedPart;
                    contentSpan.appendChild(mSpan);
                    if (remPart) {
                        const rSpan = document.createElement('strong');
                        rSpan.className = 'suggestion-completion';
                        rSpan.textContent = remPart;
                        contentSpan.appendChild(rSpan);
                    }
                } else if (queryWords.some(qw => tokenClean.includes(qw))) {
                    const mSpan = document.createElement('span');
                    mSpan.className = 'suggestion-matched';
                    mSpan.textContent = token;
                    contentSpan.appendChild(mSpan);
                } else {
                    const span = document.createElement('span');
                    span.className = 'suggestion-word';
                    span.textContent = token;
                    contentSpan.appendChild(span);
                }
            });
        } else {
            // Full label fallback
            const wordSpan = document.createElement('span');
            wordSpan.className = 'suggestion-word';
            wordSpan.textContent = label;
            contentSpan.appendChild(wordSpan);
        }

        item.appendChild(contentSpan);

        item.addEventListener('click', (e) => {
            e.stopPropagation();
            this.selectSuggestion(index);
        });
        item.addEventListener('mouseenter', () => {
            this.selectedIndex = index;
            this.updateSelection();
        });

        return item;
    }

    showLoading() {
        this.dropdown.innerHTML = `
            <div class="word-suggestion-loading">
                <i class="fas fa-spinner fa-spin"></i>
                Finding suggestions...
            </div>
        `;
        this.showDropdown();
    }

    showEmptyState() {
        // Fix XSS vulnerability by using textContent
        const emptyDiv = document.createElement('div');
        emptyDiv.className = 'word-suggestion-empty';
        emptyDiv.innerHTML = '<i class="fas fa-search"></i>';

        const p = document.createElement('p');
        p.textContent = `No suggestions found for "${this.input.value}"`;
        emptyDiv.appendChild(p);

        this.dropdown.innerHTML = '';
        this.dropdown.appendChild(emptyDiv);
    }

    showErrorState() {
        this.dropdown.innerHTML = `
            <div class="word-suggestion-empty">
                <i class="fas fa-exclamation-triangle"></i>
                <p>Error loading suggestions. Please try again.</p>
            </div>
        `;
    }

    // ----------- NAVIGATION -----------

    navigateDown() {
        if (this.suggestions.length === 0)
            return;



        this.selectedIndex = (this.selectedIndex + 1) % this.suggestions.length;
        this.updateSelection();
    }

    navigateUp() {
        if (this.suggestions.length === 0)
            return;



        this.selectedIndex = (this.selectedIndex - 1 + this.suggestions.length) % this.suggestions.length;
        this.updateSelection();
    }

    updateSelection() {
        const items = this.dropdown.querySelectorAll('.word-suggestion-item');
        items.forEach((item, index) => {
            const isSelected = index === this.selectedIndex;
            item.classList.toggle('selected', isSelected);
            item.setAttribute('aria-selected', isSelected);
            if (isSelected) {
                item.scrollIntoView({ block: 'nearest' });
            }
        });
    }

    // ----------- SELECTION -----------

    selectSuggestion(index = null) {
        const selectedIndex = index !== null ? index : this.selectedIndex;
        if (selectedIndex < 0 || selectedIndex >= this.suggestions.length)
            return;

        const suggestionItem = this.suggestions[selectedIndex];
        const isObject = typeof suggestionItem === 'object' && suggestionItem !== null;
        const label = isObject ? (suggestionItem.label || '') : String(suggestionItem);
        const currentValue = this.input.value;

        // Cancel pending debounce and abort in-flight fetch
        clearTimeout(this.debounceTimer);
        if (this.abortController) {
            this.abortController.abort();
        }

        this.isSelecting = true;

        if (this.options.multiWord) {
            this.input.value = this.replaceLastWord(currentValue, label) + ' ';
        } else {
            this.input.value = label;
        }

        // Clear suggestions list and close dropdown immediately
        this.suggestions = [];
        this.selectedIndex = -1;
        this.dropdown.innerHTML = '';
        this.hideDropdown();

        // Fire input-specific event
        this.input.dispatchEvent(new CustomEvent('wordSelected', {
            detail: {
                originalWord: currentValue,
                suggestedWord: label,
                item: suggestionItem,
                fullText: this.input.value
            }
        }));

        this.input.dispatchEvent(new Event('input', { bubbles: true }));

        if (typeof this.options.onSuggestionSelected === 'function') {
            this.options.onSuggestionSelected(label, this.input, suggestionItem);
        }

        setTimeout(() => {
            this.isSelecting = false;
        }, 100);
    }

    // ----------- OVERLAY HELPERS -----------

    getFocusBlurOverlay() {
        let overlay = document.getElementById('focus-blur-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'focus-blur-overlay';
            overlay.className = 'focus-blur-overlay';
            overlay.style.display = 'none';
            document.body.appendChild(overlay);
        }
        return overlay;
    }

    showBlurOverlay() {
        const overlay = this.getFocusBlurOverlay();
        overlay.style.display = 'block';
    }

    hideBlurOverlay() {
        const overlay = document.getElementById('focus-blur-overlay');
        if (!overlay) return;
        // Keep overlay visible only if another WordSuggestion, Select2, or Date dropdown is open
        const anyWordSuggestionOpen = document.querySelector('.word-suggestion-dropdown.show');
        const anySelect2Open = document.querySelector('.select2-container--open');
        const anyDateDropdownOpen = document.querySelector('.multipleSelection.dropdown-elevated');
        if (!anyWordSuggestionOpen && !anySelect2Open && !anyDateDropdownOpen) {
            overlay.style.display = 'none';
        }
    }

    // ----------- UTILS -----------

    showDropdown() {
        // Never open dropdown if the related input is not focused
        if (document.activeElement !== this.input) {
            return;
        }

        this.dropdown.classList.add('show');
        this.dropdown.setAttribute('aria-hidden', 'false');
        if (this.container) {
            this.container.classList.add('dropdown-open');
        }

        // Show background blur overlay
        this.showBlurOverlay();

        // Attach listeners to capture clicks/mousedown, touches, and focus changes outside
        document.addEventListener('mousedown', this.boundHandleOutsideAction, true);
        document.addEventListener('touchstart', this.boundHandleOutsideAction, true);
        document.addEventListener('focusin', this.boundHandleOutsideAction, true);
    }

    hideDropdown() {
        this.dropdown.classList.remove('show');
        this.dropdown.setAttribute('aria-hidden', 'true');
        if (this.container) {
            this.container.classList.remove('dropdown-open');
        }

        // Hide background blur overlay
        this.hideBlurOverlay();

        // Remove outside action listeners
        document.removeEventListener('mousedown', this.boundHandleOutsideAction, true);
        document.removeEventListener('touchstart', this.boundHandleOutsideAction, true);
        document.removeEventListener('focusin', this.boundHandleOutsideAction, true);
    }

    // ----------- PUBLIC METHODS -----------

    setUrl(url) {
        this.options.url = url;
    }

    clear() {
        this.input.value = '';
        this.suggestions = [];
        this.selectedIndex = -1;
        this.dropdown.innerHTML = '';
        this.hideDropdown();
    }

    destroy() {
        this.hideDropdown();

        if (this.dropdown)
            this.dropdown.remove();

        if (this.wrapper && this.wrapper.parentNode) {
            this.wrapper.parentNode.insertBefore(this.input, this.wrapper);
            this.wrapper.remove();
            this.wrapper = null;
        }

        if (this.container) {
            this.container.classList.remove('dropdown-open');
        }

        if (this.debounceTimer)
            clearTimeout(this.debounceTimer);

        if (this.abortController)
            this.abortController.abort();

        this.input.removeEventListener('input', this.boundHandleInput);
        this.input.removeEventListener('keydown', this.boundHandleKeydown);
        this.input.removeEventListener('focus', this.boundHandleFocus);
        this.input.removeEventListener('blur', this.boundHandleBlur);
        document.removeEventListener('mousedown', this.boundHandleOutsideAction, true);
        document.removeEventListener('touchstart', this.boundHandleOutsideAction, true);
        document.removeEventListener('focusin', this.boundHandleOutsideAction, true);
    }
}

// Helper function
function initWordSuggestion(inputElement, suggestionUrl, options = {}) {
    if (!inputElement || !suggestionUrl) {
        console.error('WordSuggestion: inputElement and suggestionUrl are required');
        return null;
    }
    const instance = new WordSuggestion(inputElement, suggestionUrl, options);
    inputElement.wordSuggestion = instance;
    return instance;
}

// Make function globally available
window.initWordSuggestion = initWordSuggestion;

// Lightweight jQuery wrapper for word suggestions (only if jQuery not available)
if (typeof window.$ === 'undefined') {
    function $(selector) {
        const elements = typeof selector === "string" ? document.querySelectorAll(selector) : [selector];
        return {
            wordSuggestion: function (options = {}) {
                elements.forEach((element) => {
                    if (!element) return;

                    const config = {
                        url: options.url || "",
                        placeholder: options.placeholder || "Type to search...",
                        minLength: options.minLength || 2,
                        debounceDelay: options.debounceDelay || 300,
                        maxSuggestions: options.maxSuggestions || 5,
                        onSelect: options.onSelect || null,
                        allowSpaces: options.allowSpaces !== undefined ? options.allowSpaces : true,
                        multiWord: options.multiWord !== undefined ? options.multiWord : false,
                        ...options
                    };

                    if (!config.url) {
                        console.error("WordSuggestion: URL is required");
                        return;
                    }

                    initWordSuggestion(element, config.url, {
                        debounceDelay: config.debounceDelay,
                        minQueryLength: config.minLength,
                        maxSuggestions: config.maxSuggestions,
                        onSuggestionSelected: config.onSelect,
                        allowSpaces: config.allowSpaces,
                        multiWord: config.multiWord
                    });
                });
                return this;
            }
        };
    }
    window.$ = $;
} else {
    // Extend existing jQuery with wordSuggestion plugin
    window.$.fn.wordSuggestion = function (options = {}) {
        return this.each(function () {
            const element = this;
            const config = {
                url: options.url || "",
                placeholder: options.placeholder || "Type to search...",
                minLength: options.minLength || 2,
                debounceDelay: options.debounceDelay || 300,
                maxSuggestions: options.maxSuggestions || 5,
                onSelect: options.onSelect || null,
                allowSpaces: options.allowSpaces !== undefined ? options.allowSpaces : true,
                multiWord: options.multiWord !== undefined ? options.multiWord : false,
                ...options
            };

            if (!config.url) {
                console.error("WordSuggestion: URL is required");
                return;
            }

            initWordSuggestion(element, config.url, {
                debounceDelay: config.debounceDelay,
                minQueryLength: config.minLength,
                maxSuggestions: config.maxSuggestions,
                onSuggestionSelected: config.onSelect,
                allowSpaces: config.allowSpaces,
                multiWord: config.multiWord
            });
        });
    };
}

// Export for modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = WordSuggestion;
}
