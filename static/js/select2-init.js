/**
 * Select2 Initialization Helper
 * Ensures Select2 is available before initializing forms
 */

window.Select2Helper = {
    // Check if Select2 is available
    isAvailable: function () {
        return typeof $ !== 'undefined' && typeof $.fn !== 'undefined' && typeof $.fn.select2 !== 'undefined';
    },

    // Wait for Select2 to be available
    waitForSelect2: function (callback, maxAttempts = 50) {
        let attempts = 0;
        const self = this;

        function check() {
            attempts++;
            if (self.isAvailable()) {
                callback();
            } else if (attempts < maxAttempts) {
                setTimeout(check, 100);
            } else {
                console.warn('Select2 failed to load after maximum attempts');
            }
        }

        check();
    },

    // Initialize Select2 on specific elements
    init: function (selectors, options = {}) {
        const defaultOptions = {
            placeholder: "Type to search...",
            allowClear: true,
            width: '100%'
        };

        const finalOptions = Object.assign({}, defaultOptions, options);

        this.waitForSelect2(() => {
            $(selectors).select2(finalOptions);
        });
    },

    // Initialize with custom options
    initCustom: function (selectors, customOptions) {
        this.waitForSelect2(() => {
            $(selectors).each(function () {
                const $this = $(this);
                const options = Object.assign({}, customOptions);
                $this.select2(options);
            });
        });
    },

    // Initialize all form selects (only if Select2 is available)
    initAllForms: function () {
        this.waitForSelect2(() => {
            // Only initialize selects that have specific classes or are in forms that need Select2
            $('select[id^="id_"][class*="select2"], select[data-select2="true"]').each(function () {
                const $this = $(this);
                if (!$this.hasClass('select2-hidden-accessible')) {
                    $this.select2({
                        placeholder: "Type to search...",
                        allowClear: true,
                        width: '100%'
                    });
                }
            });
        });
    }
};

// Auto-initialize on DOM ready (only if Select2 is needed)
document.addEventListener('DOMContentLoaded', function () {
    // Check if there are any forms that actually need Select2
    const needsSelect2 = document.querySelector('select[id^="id_"][class*="select2"], select[data-select2="true"]');

    if (needsSelect2) {
        // Wait for jQuery to be available
        function waitForJQuery() {
            if (typeof $ !== 'undefined') {
                // Small delay to ensure all scripts are loaded
                setTimeout(function () {
                    Select2Helper.initAllForms();
                }, 200);
            } else {
                setTimeout(waitForJQuery, 100);
            }
        }
        waitForJQuery();
    }
});

// Global Select2 focus-blur behavior
(function () {
    function ensureOverlay() {
        var existing = document.getElementById('focus-blur-overlay');
        if (existing) return existing;
        var overlay = document.createElement('div');
        overlay.id = 'focus-blur-overlay';
        overlay.className = 'focus-blur-overlay';
        overlay.style.display = 'none';
        overlay.addEventListener('mousedown', function () {
            var openDropdown = document.querySelector('.select2-container--open');
            if (openDropdown) {
                var select = $(openDropdown).prev('select');
                if (select && select.length) select.select2('close');
            }
        });
        document.body.appendChild(overlay);
        return overlay;
    }

    function showOverlay() { ensureOverlay().style.display = 'block'; }
    function hideOverlay() { var o = document.getElementById('focus-blur-overlay'); if (o) o.style.display = 'none'; }

    function elevateSelect2($select) {
        try {
            var container = $select.data('select2')?.$container?.get(0);
            if (container) container.classList.add('elevate-focus');
        } catch (e) { }
    }
    function resetElevation($select) {
        try {
            var container = $select.data('select2')?.$container?.get(0);
            if (container) container.classList.remove('elevate-focus');
        } catch (e) { }
    }

    if (typeof window !== 'undefined') {
        function bindHandlers() {
            if (!window.jQuery) { setTimeout(bindHandlers, 100); return; }

            // Track if focus came from keyboard (Tab) vs mouse
            var keyboardFocus = false;
            var lastTabTime = 0;

            // Detect Tab key press
            $(document).on('keydown', function (e) {
                if (e.key === 'Tab' || e.keyCode === 9) {
                    keyboardFocus = true;
                    lastTabTime = Date.now();
                    // Reset after a short delay
                    setTimeout(function () { keyboardFocus = false; }, 200);
                }
            });

            // Auto-open Select2 dropdown when focused via keyboard (Tab)
            $(document).on('focus', 'select.select2-hidden-accessible', function (e) {
                var $select = $(e.target);
                // Check if focus came from keyboard (within 200ms of Tab press)
                var timeSinceTab = Date.now() - lastTabTime;
                if ((keyboardFocus || timeSinceTab < 200) && $select.data('select2')) {
                    // Small delay to ensure Select2 is ready
                    setTimeout(function () {
                        try {
                            var select2Instance = $select.data('select2');
                            if (select2Instance && !select2Instance.isOpen()) {
                                $select.select2('open');
                            }
                        } catch (err) {
                            // Silently fail if Select2 isn't fully initialized
                        }
                    }, 10);
                }
            });

            // Also handle focus on Select2 container (the visible element)
            $(document).on('focus', '.select2-selection, .select2-search__field', function (e) {
                // Find the associated select element
                var $container = $(e.target).closest('.select2-container');
                if ($container.length) {
                    var $select = $container.prev('select');
                    if ($select.length && $select.data('select2')) {
                        var timeSinceTab = Date.now() - lastTabTime;
                        if ((keyboardFocus || timeSinceTab < 200)) {
                            setTimeout(function () {
                                try {
                                    var select2Instance = $select.data('select2');
                                    if (select2Instance && !select2Instance.isOpen()) {
                                        $select.select2('open');
                                    }
                                } catch (err) {
                                    // Silently fail if Select2 isn't fully initialized
                                }
                            }, 10);
                        }
                    }
                }
            });

            // Suppress browser native tooltip on placeholder
            $(document).on('mouseenter', '.select2-selection__rendered[title]', function () {
                var $this = $(this);
                if ($this.find('.select2-selection__placeholder').length || $this.attr('title') === 'Type to search...') {
                    $this.removeAttr('title');
                }
            });

            $(document)
                .on('select2:open', function (e) {
                    showOverlay();
                    elevateSelect2($(e.target));
                })
                .on('select2:close', function (e) {
                    resetElevation($(e.target));
                    setTimeout(function () {
                        var anyOpen = document.querySelector('.select2-container--open');
                        if (!anyOpen) hideOverlay();
                    }, 0);
                });
        }
        bindHandlers();
    }
})();