/**
 * Form Submit Guard - Prevents duplicate form submissions
 * Works with both regular forms and AJAX forms
 * 
 * SECURE BY DEFAULT MODE:
 * - All forms are automatically protected
 * - Use data-allow-double-submit to opt-out specific forms
 * 
 * Usage:
 * 1. Include this script - all forms are protected automatically
 * 2. To allow double-submit: <form data-allow-double-submit>
 * 3. Manual control: FormSubmitGuard.reset(formId) or .complete(formId)
 */

(function (window) {
    'use strict';

    const FormSubmitGuard = {
        // Track active submissions
        activeSubmissions: new Set(),
        // Map elements to their submission IDs
        elementToIdMap: new WeakMap(),
        // Track protected forms to avoid duplicate listeners
        protectedForms: new WeakSet(),

        // Default options
        defaults: {
            autoProtect: true, // ✨ SECURE BY DEFAULT
            disableButton: true,
            showSpinner: true,
            restoreOnError: true,
            restoreDelay: 3000, // Auto-restore after 3s if no response
            buttonText: {
                submitting: 'Submitting...',
                submitted: 'Submitted'
            }
        },

        /**
         * Initialize - Auto-protect all forms (except those with data-allow-double-submit)
         */
        init: function (options = {}) {
            const config = { ...this.defaults, ...options };

            if (config.autoProtect) {
                // Protect ALL forms by default
                document.querySelectorAll('form').forEach(form => {
                    // Skip forms that explicitly allow double-submit
                    if (form.hasAttribute('data-allow-double-submit')) {
                        return;
                    }

                    // Skip already protected forms
                    if (!this.protectedForms.has(form)) {
                        this.protectForm(form, config);
                    }
                });
            } else {
                // Legacy mode: Only protect forms with data-prevent-double-submit
                document.querySelectorAll('form[data-prevent-double-submit]').forEach(form => {
                    if (!this.protectedForms.has(form)) {
                        this.protectForm(form, config);
                    }
                });
            }

            // Protect individual buttons with data attribute
            document.querySelectorAll('button[data-prevent-double-submit], input[type="submit"][data-prevent-double-submit]').forEach(button => {
                this.protectButton(button, config);
            });
        },

        /**
         * Protect a form from double submission
         */
        protectForm: function (form, options = {}) {
            const config = { ...this.defaults, ...options };
            const formId = form.id || `form_${Date.now()}_${Math.random()}`;
            // Mark as protected and store mapping
            this.protectedForms.add(form);
            this.elementToIdMap.set(form, formId);

            // Get ALL submit buttons to track clicks
            const allSubmitButtons = Array.from(
                form.querySelectorAll('button[type="submit"], input[type="submit"]')
            );

            // Track which button was clicked and preserve its value
            // This MUST happen on click, not mousedown, to ensure we capture the value
            allSubmitButtons.forEach(btn => {
                btn.addEventListener('click', function (e) {
                    const buttonName = btn.getAttribute('name');
                    const buttonValue = btn.getAttribute('value');

                    // If button has name and value, preserve it immediately
                    if (buttonName && buttonValue !== null) {
                        // Remove any existing hidden field with this name
                        const existingFields = form.querySelectorAll(`input[type="hidden"][name="${buttonName}"]`);
                        existingFields.forEach(field => field.remove());

                        // Create hidden field immediately to preserve button value
                        const hiddenField = document.createElement('input');
                        hiddenField.type = 'hidden';
                        hiddenField.name = buttonName;
                        hiddenField.value = buttonValue;
                        // Insert at the beginning of the form
                        form.insertBefore(hiddenField, form.firstChild);

                        console.debug('FormSubmitGuard: Preserved button value on click', {
                            name: buttonName,
                            value: buttonValue
                        });
                    }

                    // Also mark for detection in submit handler (backup)
                    btn.dataset.wasClicked = 'true';
                    allSubmitButtons.forEach(otherBtn => {
                        if (otherBtn !== btn) {
                            delete otherBtn.dataset.wasClicked;
                        }
                    });
                }, { capture: true });
            });

            form.addEventListener('submit', function (e) {
                // Check if already submitting
                if (FormSubmitGuard.activeSubmissions.has(formId)) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                    return false;
                }

                // Mark as submitting IMMEDIATELY
                FormSubmitGuard.activeSubmissions.add(formId);

                // The actual button that was clicked - use multiple fallback methods
                // Note: allSubmitButtons is already defined above in protectForm
                let clickedButton = null;

                // Method 1: Modern browsers support e.submitter
                if (e.submitter && (e.submitter.type === 'submit' || e.submitter.tagName === 'BUTTON')) {
                    clickedButton = e.submitter;
                }
                // Method 2: Check document.activeElement (the focused element when form was submitted)
                else if (document.activeElement &&
                    (document.activeElement.type === 'submit' ||
                        (document.activeElement.tagName === 'BUTTON' && document.activeElement.type !== 'button'))) {
                    clickedButton = document.activeElement;
                }
                // Method 3: Check which button was recently clicked (stored in data attribute)
                else {
                    allSubmitButtons.forEach(btn => {
                        if (btn.dataset.wasClicked === 'true') {
                            clickedButton = btn;
                            delete btn.dataset.wasClicked;
                        }
                    });
                }

                // Fallback: Use first button if none detected
                if (!clickedButton && allSubmitButtons.length > 0) {
                    clickedButton = allSubmitButtons[0];
                }

                // Note: Button values are already preserved in hidden fields by the click handler above
                // This is just for logging/debugging purposes
                if (clickedButton) {
                    const buttonName = clickedButton.getAttribute('name');
                    const buttonValue = clickedButton.getAttribute('value');

                    if (buttonName && buttonValue !== null) {
                        // CRITICAL FIX: Ensure hidden field exists before disabling buttons
                        // If the click handler didn't catch it (e.g. form submitted via Enter key on input),
                        // we must add it here or the value will be lost when button is disabled.
                        if (!form.querySelector(`input[type="hidden"][name="${buttonName}"]`)) {
                            const hiddenField = document.createElement('input');
                            hiddenField.type = 'hidden';
                            hiddenField.name = buttonName;
                            hiddenField.value = buttonValue;
                            form.insertBefore(hiddenField, form.firstChild);

                            console.debug('FormSubmitGuard: Created fallback hidden field in submit handler', {
                                name: buttonName,
                                value: buttonValue
                            });
                        } else {
                            console.debug('FormSubmitGuard: Submit detected (hidden field already exists)', {
                                name: buttonName,
                                value: buttonValue
                            });
                        }
                    }
                }

                // Store original state for ALL buttons
                const buttonStates = new Map();
                allSubmitButtons.forEach(btn => {
                    buttonStates.set(btn, {
                        disabled: btn.disabled,
                        text: btn.textContent?.trim() || btn.value || '',
                        innerHTML: btn.innerHTML
                    });

                    // Store in dataset for reset() method
                    if (!btn.dataset.originalText) {
                        btn.dataset.originalText = btn.textContent?.trim() || btn.value || '';
                        if (btn.tagName !== 'INPUT') {
                            btn.dataset.originalInnerHTML = btn.innerHTML;
                        }
                    }

                    // Disable ALL buttons immediately
                    btn.disabled = true;
                });

                // Show loading state ONLY on clicked button
                if (clickedButton && config.showSpinner) {
                    FormSubmitGuard.setSubmittingState(clickedButton, config);
                }

                // Handle form completion
                const handleComplete = function () {
                    FormSubmitGuard.activeSubmissions.delete(formId);

                    // Restore ALL buttons
                    if (config.restoreOnError) {
                        allSubmitButtons.forEach(btn => {
                            const originalState = buttonStates.get(btn);
                            if (originalState) {
                                btn.disabled = originalState.disabled;
                                btn.classList.remove('submitting');

                                if (btn.tagName === 'INPUT') {
                                    btn.value = originalState.text;
                                } else {
                                    btn.innerHTML = originalState.innerHTML;
                                }
                            }
                        });
                    }
                };

                // Listen for AJAX events
                form.addEventListener('ajax:success', handleComplete, { once: true });
                form.addEventListener('ajax:error', handleComplete, { once: true });
                form.addEventListener('ajax:complete', handleComplete, { once: true });

                // Auto-restore after timeout for non-AJAX forms
                if (!form.hasAttribute('data-ajax-form')) {
                    setTimeout(handleComplete, config.restoreDelay);
                }
            });
        },

        /**
         * Protect a button from double clicks
         */
        protectButton: function (button, options = {}) {
            const config = { ...this.defaults, ...options };
            const buttonId = button.id || `btn_${Date.now()}_${Math.random()}`;
            // Store mapping for later retrieval
            this.elementToIdMap.set(button, buttonId);

            button.addEventListener('click', function (e) {
                // Check if already submitting
                if (FormSubmitGuard.activeSubmissions.has(buttonId)) {
                    e.preventDefault();
                    e.stopPropagation();
                    return false;
                }

                // Only protect if it's a submit button or has submit behavior
                if (button.type !== 'submit' && !button.closest('form')) {
                    return;
                }

                // Mark as submitting
                FormSubmitGuard.activeSubmissions.add(buttonId);

                // Store original state
                const originalState = {
                    disabled: button.disabled,
                    text: button.textContent || button.value,
                    innerHTML: button.innerHTML
                };

                // Set submitting state
                if (config.disableButton) {
                    FormSubmitGuard.setSubmittingState(button, config);
                }

                // Restore after delay or on completion
                const handleComplete = function () {
                    FormSubmitGuard.activeSubmissions.delete(buttonId);
                    if (config.restoreOnError) {
                        setTimeout(() => {
                            if (FormSubmitGuard.activeSubmissions.has(buttonId)) {
                                FormSubmitGuard.restoreButtonState(button, originalState);
                            }
                        }, config.restoreDelay);
                    }
                };

                // Listen for custom events (for AJAX)
                button.addEventListener('ajax:success', handleComplete, { once: true });
                button.addEventListener('ajax:error', handleComplete, { once: true });
                button.addEventListener('ajax:complete', handleComplete, { once: true });

                // Auto-restore after timeout
                setTimeout(handleComplete, config.restoreDelay);
            });
        },

        /**
         * Set button to submitting state
         */
        setSubmittingState: function (button, config) {
            button.disabled = true;
            button.classList.add('submitting');

            if (config.showSpinner) {
                const spinner = '<i class="fas fa-spinner fa-spin"></i> ';
                if (button.tagName === 'INPUT') {
                    button.value = config.buttonText.submitting || 'Submitting...';
                } else {
                    button.innerHTML = spinner + (config.buttonText.submitting || button.dataset.originalText || 'Submitting...');
                }
            }
        },

        /**
         * Restore button to original state
         */
        restoreButtonState: function (button, originalState) {
            if (!button) return;

            button.disabled = originalState.disabled;
            button.classList.remove('submitting', 'submitted');

            if (button.tagName === 'INPUT') {
                button.value = originalState.text;
            } else {
                button.innerHTML = originalState.innerHTML;
            }
        },

        /**
         * Mark submission as complete (graceful finish)
         * Shows brief success state, then restores after delay
         */
        complete: function (formOrButton) {
            const element = typeof formOrButton === 'string'
                ? document.getElementById(formOrButton)
                : formOrButton;

            if (!element) return;

            const id = this.elementToIdMap.get(element) || element.id;
            if (id) {
                this.activeSubmissions.delete(id);
            }

            const buttons = element.tagName === 'FORM'
                ? Array.from(element.querySelectorAll('button[type="submit"], input[type="submit"]'))
                : [element];

            buttons.forEach(btn => {
                btn.classList.remove('submitting');
                btn.classList.add('submitted');

                if (btn.tagName === 'INPUT') {
                    btn.value = '✓ Submitted';
                } else {
                    btn.innerHTML = '<i class="fas fa-check"></i> Submitted';
                }
            });

            // Restore after short delay (only once, not per button)
            setTimeout(() => this.reset(element), 1500);
        },

        /**
         * Immediately reset to normal state (for errors/retries)
         */
        reset: function (formOrButton) {
            const element = typeof formOrButton === 'string'
                ? document.getElementById(formOrButton)
                : formOrButton;

            if (!element) return;

            const id = this.elementToIdMap.get(element) || element.id;
            if (id) {
                this.activeSubmissions.delete(id);
            }

            const buttons = element.tagName === 'FORM'
                ? Array.from(element.querySelectorAll('button[type="submit"], input[type="submit"]'))
                : [element];

            buttons.forEach(btn => {
                btn.disabled = false;
                btn.classList.remove('submitting', 'submitted');

                if (btn.dataset.originalText) {
                    if (btn.tagName === 'INPUT') {
                        btn.value = btn.dataset.originalText;
                    } else {
                        btn.innerHTML = btn.dataset.originalInnerHTML || btn.dataset.originalText;
                    }
                    delete btn.dataset.originalText;
                    delete btn.dataset.originalInnerHTML;
                }
            });
        },

        /**
         * Alias for better readability
         */
        enable: function (formOrButton) {
            return this.reset(formOrButton);
        },

        /**
         * Check if form/button is currently submitting
         */
        isSubmitting: function (formOrButton) {
            const element = typeof formOrButton === 'string'
                ? document.getElementById(formOrButton)
                : formOrButton;

            if (!element) return false;

            const id = this.elementToIdMap.get(element) || element.id;
            return id ? this.activeSubmissions.has(id) : false;
        },

        /**
         * Manually protect a form (useful for dynamically added forms)
         */
        protect: function (formOrButton, options = {}) {
            const element = typeof formOrButton === 'string'
                ? document.getElementById(formOrButton)
                : formOrButton;

            if (!element) return;

            if (element.tagName === 'FORM') {
                this.protectForm(element, options);
            } else {
                this.protectButton(element, options);
            }
        }
    };

    // Auto-initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => FormSubmitGuard.init());
    } else {
        FormSubmitGuard.init();
    }

    // Expose globally
    window.FormSubmitGuard = FormSubmitGuard;

})(window);

