// ========================================
// BILLING SYSTEM - MAIN JAVASCRIPT
// ========================================

function initMain() {
    // Theme Toggle Functionality
    const themeToggle = document.getElementById('themeToggle');
    const html = document.documentElement;
    const body = document.body;

    // Disable autocomplete on all forms
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.setAttribute('autocomplete', 'off');
    });

    function updateThemeIcon(theme) {
        if (!themeToggle) return;
        const icon = themeToggle.querySelector('i');
        if (icon) {
            if (theme === 'dark') {
                icon.className = 'fas fa-sun';
            } else {
                icon.className = 'fas fa-moon';
            }
        }
    }

    function setTheme(theme) {
        html.setAttribute('data-theme', theme);
        body.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
        updateThemeIcon(theme);
    }

    // Check for saved theme preference or default to 'light'
    const currentTheme = localStorage.getItem('theme') || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    setTheme(currentTheme);

    if (themeToggle && !themeToggle.dataset.themeInitialized) {
        themeToggle.dataset.themeInitialized = 'true';
        themeToggle.addEventListener('click', () => {
            const activeTheme = html.getAttribute('data-theme') || body.getAttribute('data-theme') || 'light';
            const newTheme = activeTheme === 'dark' ? 'light' : 'dark';

            setTheme(newTheme);

            // Notify other components (e.g. charts) that the theme changed
            document.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme: newTheme } }));
        });
    }

    // Auto-detect system theme preference if not set
    if (localStorage.getItem('theme') === null) {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        const theme = prefersDark ? 'dark' : 'light';
        body.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
        updateThemeIcon(theme);
    }

    // Initialize Animated Counters
    if (typeof initializeCounters === 'function') {
        initializeCounters();
    }

    // Initialize Indian Number Formatting on Inputs
    if (typeof formatIndianNumber === 'function') {
        document.querySelectorAll('.indian-number').forEach(input => {
            const maxDecimals = parseInt(input.dataset.decimals) || 2;

            if (input.value) {
                input.value = formatIndianNumber(input.value, maxDecimals);
            }

            input.addEventListener('input', function(e) {
                const cursorPos = e.target.selectionStart;
                const oldLength = e.target.value.length;

                const formatted = formatIndianNumber(e.target.value, maxDecimals);
                e.target.value = formatted;

                const newLength = formatted.length;
                const diff = newLength - oldLength;
                e.target.setSelectionRange(cursorPos + diff, cursorPos + diff);
            });

            input.addEventListener('blur', function(e) {
                let value = e.target.value;
                if (value.endsWith('.')) {
                    value = value.slice(0, -1);
                }
                if (maxDecimals > 0 && !value.includes('.') && value !== '') {
                    value += '.00';
                }
                e.target.value = value;
            });
        });

        // Remove commas before form submission
        document.querySelectorAll('form').forEach(form => {
            form.addEventListener('submit', function() {
                form.querySelectorAll('.indian-number').forEach(input => {
                    input.value = input.value.replace(/,/g, '');
                });
            });
        });
    }

    // Navigation enhancements
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach((item, index) => {
        item.style.setProperty('--item-index', index);

        // Add ripple effect on click
        item.addEventListener('click', function (e) {
            const ripple = document.createElement('span');
            const rect = this.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            const x = e.clientX - rect.left - size / 2;
            const y = e.clientY - rect.top - size / 2;

            ripple.style.width = ripple.style.height = size + 'px';
            ripple.style.left = x + 'px';
            ripple.style.top = y + 'px';
            ripple.classList.add('ripple');

            this.appendChild(ripple);

            setTimeout(() => {
                ripple.remove();
            }, 600);
        });
    });

    // Add smooth scroll to dropdown items
    const dropdownItems = document.querySelectorAll('.dropdown-item');
    dropdownItems.forEach(item => {
        item.addEventListener('mouseenter', function () {
            this.style.transform = 'translateX(8px) scale(1.02)';
        });

        item.addEventListener('mouseleave', function () {
            this.style.transform = 'translateX(0) scale(1)';
        });
    });

    // Parallax effect for navbar (desktop only — on mobile .navbar is the sidebar)
    let ticking = false;
    function updateNavbar() {
        if (window.innerWidth <= 768) return; // Sidebar mode: skip parallax
        const navbar = document.querySelector('.navbar');
        if (!navbar) return;
        const scrolled = window.pageYOffset;
        const rate = scrolled * -0.5;

        if (scrolled > 50) {
            navbar.style.transform = `translateY(${rate}px)`;
            navbar.style.backdropFilter = 'blur(20px)';
        } else {
            navbar.style.transform = 'translateY(0)';
            navbar.style.backdropFilter = 'blur(10px)';
        }

        ticking = false;
    }

    function requestTick() {
        if (!ticking) {
            requestAnimationFrame(updateNavbar);
            ticking = true;
        }
    }

    window.addEventListener('scroll', requestTick, { passive: true });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMain);
} else {
    initMain();
}

// Auto-bind click-to-copy on elements with data-copy attribute
document.addEventListener('click', function (e) {
    const el = e.target.closest('[data-copy]');
    if (el) {
        e.preventDefault();
        copyToClipboard(el.getAttribute('data-copy'));
    }
});
