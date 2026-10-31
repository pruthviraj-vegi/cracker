// Customer Admin Custom JavaScript

document.addEventListener('DOMContentLoaded', function () {

    // Enhanced table interactions
    enhanceTableInteractions();

    // Enhanced form interactions
    enhanceFormInteractions();

    // Add keyboard shortcuts
    addKeyboardShortcuts();

    // Add bulk action confirmations
    addBulkActionConfirmations();

    // Add search enhancements
    enhanceSearch();

    // Add filter enhancements
    enhanceFilters();

    // Add pagination enhancements
    enhancePagination();

    // Add responsive enhancements
    addResponsiveEnhancements();
});

function enhanceTableInteractions() {
    // Add row selection with visual feedback
    const tableRows = document.querySelectorAll('#result_list tbody tr');

    tableRows.forEach(row => {
        row.addEventListener('click', function (e) {
            // Don't trigger if clicking on action buttons or links
            if (e.target.closest('a') || e.target.closest('input')) {
                return;
            }

            // Toggle selection
            this.classList.toggle('selected-row');

            // Update checkbox if present
            const checkbox = this.querySelector('input[type="checkbox"]');
            if (checkbox) {
                checkbox.checked = !checkbox.checked;
            }
        });

        // Add hover effect
        row.addEventListener('mouseenter', function () {
            this.style.cursor = 'pointer';
        });
    });

    // Add select all functionality
    const selectAllCheckbox = document.querySelector('#action-toggle');
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function () {
            const checkboxes = document.querySelectorAll('#result_list tbody input[type="checkbox"]');
            checkboxes.forEach(checkbox => {
                checkbox.checked = this.checked;
                const row = checkbox.closest('tr');
                if (this.checked) {
                    row.classList.add('selected-row');
                } else {
                    row.classList.remove('selected-row');
                }
            });
        });
    }
}

function enhanceFormInteractions() {
    // Add real-time validation
    const form = document.querySelector('#customer_form');
    if (form) {
        const phoneInput = form.querySelector('#id_phone_number');
        const emailInput = form.querySelector('#id_email');
        const nameInput = form.querySelector('#id_name');

        // Phone number validation
        if (phoneInput) {
            phoneInput.addEventListener('input', function () {
                const value = this.value.replace(/\D/g, '');
                if (value.length > 10) {
                    value = value.substring(0, 10);
                }
                this.value = value;

                if (value.length === 10) {
                    this.style.borderColor = '#28a745';
                    showValidationMessage(this, 'Phone number is valid', 'success');
                } else if (value.length > 0) {
                    this.style.borderColor = '#dc3545';
                    showValidationMessage(this, 'Phone number must be 10 digits', 'error');
                } else {
                    this.style.borderColor = '#e9ecef';
                    hideValidationMessage(this);
                }
            });
        }

        // Email validation
        if (emailInput) {
            emailInput.addEventListener('blur', function () {
                const email = this.value;
                const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

                if (email && !emailRegex.test(email)) {
                    this.style.borderColor = '#dc3545';
                    showValidationMessage(this, 'Please enter a valid email address', 'error');
                } else if (email) {
                    this.style.borderColor = '#28a745';
                    showValidationMessage(this, 'Email format is valid', 'success');
                } else {
                    this.style.borderColor = '#e9ecef';
                    hideValidationMessage(this);
                }
            });
        }

        // Name validation
        if (nameInput) {
            nameInput.addEventListener('blur', function () {
                if (this.value.trim().length < 2) {
                    this.style.borderColor = '#dc3545';
                    showValidationMessage(this, 'Name must be at least 2 characters', 'error');
                } else {
                    this.style.borderColor = '#28a745';
                    showValidationMessage(this, 'Name is valid', 'success');
                }
            });
        }
    }
}

function showValidationMessage(element, message, type) {
    // Remove existing validation message
    hideValidationMessage(element);

    // Create validation message
    const validationDiv = document.createElement('div');
    validationDiv.className = `validation-message validation-${type}`;
    validationDiv.textContent = message;
    validationDiv.style.cssText = `
        font-size: 12px;
        margin-top: 4px;
        padding: 4px 8px;
        border-radius: 4px;
        color: ${type === 'success' ? '#155724' : '#721c24'};
        background: ${type === 'success' ? '#d4edda' : '#f8d7da'};
        border: 1px solid ${type === 'success' ? '#c3e6cb' : '#f5c6cb'};
    `;

    // Insert after the input field
    element.parentNode.insertBefore(validationDiv, element.nextSibling);
}

function hideValidationMessage(element) {
    const existingMessage = element.parentNode.querySelector('.validation-message');
    if (existingMessage) {
        existingMessage.remove();
    }
}

function addKeyboardShortcuts() {
    // Add keyboard shortcuts for common actions
    document.addEventListener('keydown', function (e) {
        // Ctrl/Cmd + N for new customer
        if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
            e.preventDefault();
            const addButton = document.querySelector('.object-tools a[href*="add"]');
            if (addButton) {
                addButton.click();
            }
        }

        // Ctrl/Cmd + F for search
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
            e.preventDefault();
            const searchInput = document.querySelector('#searchbar');
            if (searchInput) {
                searchInput.focus();
            }
        }

        // Escape to clear search
        if (e.key === 'Escape') {
            const searchInput = document.querySelector('#searchbar');
            if (searchInput && searchInput.value) {
                searchInput.value = '';
                searchInput.form.submit();
            }
        }
    });
}

function addBulkActionConfirmations() {
    // Add confirmation for bulk actions
    const actionSelect = document.querySelector('#action');
    if (actionSelect) {
        actionSelect.addEventListener('change', function () {
            const selectedAction = this.value;
            const selectedRows = document.querySelectorAll('#result_list tbody input[type="checkbox"]:checked');

            if (selectedRows.length === 0) {
                alert('Please select at least one customer to perform this action.');
                this.value = '';
                return;
            }

            let confirmMessage = '';
            switch (selectedAction) {
                case 'activate_customers':
                    confirmMessage = `Are you sure you want to activate ${selectedRows.length} customer(s)?`;
                    break;
                case 'deactivate_customers':
                    confirmMessage = `Are you sure you want to deactivate ${selectedRows.length} customer(s)?`;
                    break;
                case 'reset_credit_balance':
                    confirmMessage = `Are you sure you want to reset credit balance for ${selectedRows.length} customer(s)?`;
                    break;
                case 'add_credit_to_selected':
                    confirmMessage = `Are you sure you want to add 100 credit to ${selectedRows.length} customer(s)?`;
                    break;
                case 'export_customer_data':
                    confirmMessage = `Are you sure you want to export data for ${selectedRows.length} customer(s)?`;
                    break;
            }

            if (confirmMessage && !confirm(confirmMessage)) {
                this.value = '';
            }
        });
    }
}

function enhanceSearch() {
    // Add search suggestions (placeholder for future enhancement)
    const searchInput = document.querySelector('#searchbar');
    if (searchInput) {
        // Add search icon
        const searchIcon = document.createElement('span');
        searchIcon.innerHTML = '🔍';
        searchIcon.style.cssText = `
            position: absolute;
            left: 10px;
            top: 50%;
            transform: translateY(-50%);
            color: #6c757d;
            pointer-events: none;
        `;

        const searchContainer = searchInput.parentNode;
        searchContainer.style.position = 'relative';
        searchContainer.appendChild(searchIcon);

        // Add padding to search input for icon
        searchInput.style.paddingLeft = '35px';

        // Add search history (localStorage)
        searchInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && this.value.trim()) {
                saveSearchHistory(this.value.trim());
            }
        });
    }
}

function saveSearchHistory(searchTerm) {
    let history = JSON.parse(localStorage.getItem('customer_search_history') || '[]');
    if (!history.includes(searchTerm)) {
        history.unshift(searchTerm);
        history = history.slice(0, 10); // Keep only last 10 searches
        localStorage.setItem('customer_search_history', JSON.stringify(history));
    }
}

function enhanceFilters() {
    // Add filter count badges
    const filterLinks = document.querySelectorAll('#changelist-filter a');
    filterLinks.forEach(link => {
        if (link.classList.contains('selected')) {
            const count = getFilterCount(link);
            if (count > 0) {
                const badge = document.createElement('span');
                badge.textContent = count;
                badge.style.cssText = `
                    background: #667eea;
                    color: white;
                    border-radius: 10px;
                    padding: 2px 6px;
                    font-size: 10px;
                    margin-left: 5px;
                `;
                link.appendChild(badge);
            }
        }
    });
}

function getFilterCount(filterLink) {
    // This would typically make an AJAX call to get the count
    // For now, return a placeholder
    return Math.floor(Math.random() * 50) + 1;
}

function enhancePagination() {
    // Add keyboard navigation for pagination
    const paginationLinks = document.querySelectorAll('.paginator a');
    paginationLinks.forEach(link => {
        link.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.click();
            }
        });
    });
}

function addResponsiveEnhancements() {
    // Add mobile-friendly enhancements
    if (window.innerWidth <= 768) {
        // Collapse filters on mobile
        const filterSection = document.querySelector('#changelist-filter');
        if (filterSection) {
            const filterToggle = document.createElement('button');
            filterToggle.textContent = 'Toggle Filters';
            filterToggle.style.cssText = `
                width: 100%;
                padding: 10px;
                background: #667eea;
                color: white;
                border: none;
                border-radius: 6px;
                margin-bottom: 10px;
                font-weight: 600;
            `;

            filterToggle.addEventListener('click', function () {
                const filterContent = filterSection.querySelector('ul');
                if (filterContent.style.display === 'none') {
                    filterContent.style.display = 'block';
                    this.textContent = 'Hide Filters';
                } else {
                    filterContent.style.display = 'none';
                    this.textContent = 'Show Filters';
                }
            });

            filterSection.insertBefore(filterToggle, filterSection.firstChild);

            // Hide filters by default on mobile
            const filterContent = filterSection.querySelector('ul');
            filterContent.style.display = 'none';
        }
    }
}



// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
    
    .selected-row {
        background-color: #e3f2fd !important;
        border-left: 4px solid #2196f3 !important;
    }
    
    .validation-message {
        animation: fadeIn 0.3s ease-out;
    }
    
    @keyframes fadeIn {
        from {
            opacity: 0;
            transform: translateY(-10px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
`;
document.head.appendChild(style); 