/**
 * Simplified Enhanced Select2 Configuration
 * Focuses on core functionality with better UX and theme support
 */

class EnhancedSelect2 {
  constructor() {
    this.init();
  }

  init() {
    this.setupSelect2();
    this.addCoreFeatures();
  }

  setupSelect2() {
    // Initialize Select2 with simplified configuration
    $('.enhanced-select2').select2({
      theme: 'enhanced',
      width: '100%',
      allowClear: true,
      placeholder: function() {
        return $(this).data('placeholder') || 'Select an option...';
      },
      minimumResultsForSearch: 0,
      closeOnSelect: true,
      dropdownParent: $('body')
    });
  }

  addCoreFeatures() {
    // Add focus management
    this.addFocusManagement();
    
    // Add theme support
    this.addThemeSupport();
    
    // Add form validation integration
    this.addValidationSupport();
    
    // Add accessibility features
    this.addAccessibilityFeatures();
  }

  addFocusManagement() {
    // Focus the input when dropdown opens
    $(document).on('select2:open', function() {
      setTimeout(() => {
        $('.select2-container--open .select2-search__field').focus();
      }, 100);
    });

    // Add focus styles
    $(document).on('select2:focus', function() {
      $(this).next('.select2-container').addClass('select2-container--focus');
    });

    $(document).on('select2:unfocus', function() {
      $(this).next('.select2-container').removeClass('select2-container--focus');
    });
  }

  addThemeSupport() {
    // Check for dark mode preference
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    if (prefersDark) {
      $('body').addClass('dark-theme');
    }

    // Listen for theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      if (e.matches) {
        $('body').addClass('dark-theme');
      } else {
        $('body').removeClass('dark-theme');
      }
    });
  }

  addValidationSupport() {
    // Handle form validation states
    $(document).on('select2:open', function() {
      const $select = $(this);
      const $container = $select.next('.select2-container');
      
      // Remove previous states
      $container.removeClass('select2-container--error select2-container--success');
      
      // Add error state if field is invalid
      if ($select.hasClass('is-invalid')) {
        $container.addClass('select2-container--error');
      } else if ($select.hasClass('is-valid')) {
        $container.addClass('select2-container--success');
      }
    });
    
    // Remove validation states on selection
    $(document).on('select2:select', function() {
      const $select = $(this);
      const $container = $select.next('.select2-container');
      
      $container.removeClass('select2-container--error select2-container--success');
      $select.removeClass('is-invalid is-valid');
    });
  }

  addAccessibilityFeatures() {
    // Add ARIA labels and roles
    $('.enhanced-select2').each(function() {
      const $select = $(this);
      const $container = $select.next('.select2-container');
      
      $container.attr('role', 'combobox');
      $container.attr('aria-expanded', 'false');
      $container.attr('aria-haspopup', 'true');
      
      // Update ARIA attributes on open/close
      $select.on('select2:open', function() {
        $container.attr('aria-expanded', 'true');
      });
      
      $select.on('select2:close', function() {
        $container.attr('aria-expanded', 'false');
      });
    });
    
    // Add keyboard navigation
    $(document).on('keydown', '.select2-container--open', function(e) {
      const $container = $(this);
      const $results = $container.find('.select2-results__options');
      const $highlighted = $results.find('.select2-results__option--highlighted');
      
      switch(e.keyCode) {
        case 38: // Up arrow
          e.preventDefault();
          this.navigateOptions($results, $highlighted, 'prev');
          break;
        case 40: // Down arrow
          e.preventDefault();
          this.navigateOptions($results, $highlighted, 'next');
          break;
        case 13: // Enter
          e.preventDefault();
          if ($highlighted.length) {
            $highlighted.trigger('click');
          }
          break;
        case 27: // Escape
          e.preventDefault();
          $container.find('.select2-selection').trigger('click');
          break;
      }
    });
  }

  navigateOptions($results, $highlighted, direction) {
    const $options = $results.find('.select2-results__option:not(.select2-results__option--disabled)');
    let $next;
    
    if (direction === 'next') {
      $next = $highlighted.nextAll('.select2-results__option:not(.select2-results__option--disabled)').first();
      if (!$next.length) {
        $next = $options.first();
      }
    } else {
      $next = $highlighted.prevAll('.select2-results__option:not(.select2-results__option--disabled)').first();
      if (!$next.length) {
        $next = $options.last();
      }
    }
    
    $highlighted.removeClass('select2-results__option--highlighted');
    $next.addClass('select2-results__option--highlighted');
    
    // Scroll to highlighted option
    this.scrollToOption($results, $next);
  }

  scrollToOption($container, $option) {
    const containerHeight = $container.height();
    const optionTop = $option.position().top;
    const optionHeight = $option.outerHeight();
    const scrollTop = $container.scrollTop();
    
    if (optionTop < 0) {
      $container.scrollTop(scrollTop + optionTop);
    } else if (optionTop + optionHeight > containerHeight) {
      $container.scrollTop(scrollTop + optionTop + optionHeight - containerHeight);
    }
  }

  // Public methods for external use
  static refresh(selector) {
    $(selector).select2('destroy');
    $(selector).select2({
      theme: 'enhanced',
      width: '100%',
      allowClear: true
    });
  }

  static setValue(selector, value) {
    $(selector).val(value).trigger('change');
  }

  static getValue(selector) {
    return $(selector).val();
  }

  static disable(selector) {
    $(selector).prop('disabled', true);
    $(selector).next('.select2-container').addClass('select2-container--disabled');
  }

  static enable(selector) {
    $(selector).prop('disabled', false);
    $(selector).next('.select2-container').removeClass('select2-container--disabled');
  }
}

// Initialize Enhanced Select2 when document is ready
$(document).ready(function() {
  new EnhancedSelect2();
  
  // Add utility functions to global scope
  window.EnhancedSelect2 = EnhancedSelect2;
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
  module.exports = EnhancedSelect2;
} 