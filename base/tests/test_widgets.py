"""
Tests for the AnimatedDatePickerWidget in base/widgets.py.

Verifies HTML output structure, attribute propagation, time mode toggling,
format_html escaping, and date/datetime format strings.
"""

from django.test import SimpleTestCase

from base.widgets import AnimatedDatePickerWidget


class AnimatedDatePickerWidgetRenderTests(SimpleTestCase):
    """Tests for AnimatedDatePickerWidget.render() output."""

    def test_renders_wrapper_div(self):
        """Widget output must be wrapped in .input-date-wrapper div."""
        widget = AnimatedDatePickerWidget()
        html = widget.render("test_field", None)
        self.assertIn('class="input-date-wrapper"', html)

    def test_renders_icon_span(self):
        """Widget output must contain the icon span with correct FA class."""
        widget = AnimatedDatePickerWidget(icon_class="fa-calendar-days")
        html = widget.render("test_field", None)
        self.assertIn('class="input-date-icon"', html)
        self.assertIn("fa-calendar-days", html)

    def test_renders_input_with_classes(self):
        """Widget must render an input with form-input and form-date-input classes."""
        widget = AnimatedDatePickerWidget()
        html = widget.render("test_field", None)
        self.assertIn("form-input", html)
        self.assertIn("form-date-input", html)

    def test_time_enabled_sets_data_attribute(self):
        """When enable_time=True, data-datepicker-time should be 'true'."""
        widget = AnimatedDatePickerWidget(enable_time=True)
        html = widget.render("test_field", None)
        self.assertIn('data-datepicker-time="true"', html)

    def test_time_disabled_sets_data_attribute(self):
        """When enable_time=False, data-datepicker-time should be 'false'."""
        widget = AnimatedDatePickerWidget(enable_time=False)
        html = widget.render("test_field", None)
        self.assertIn('data-datepicker-time="false"', html)

    def test_readonly_attribute_present(self):
        """The input should have readonly to prevent manual typing."""
        widget = AnimatedDatePickerWidget()
        html = widget.render("test_field", None)
        self.assertIn("readonly", html)

    def test_autocomplete_off(self):
        """Autocomplete should be disabled to avoid browser date pickers."""
        widget = AnimatedDatePickerWidget()
        html = widget.render("test_field", None)
        self.assertIn('autocomplete="off"', html)

    def test_custom_placeholder_propagated(self):
        """Custom placeholder from attrs should appear in the output."""
        widget = AnimatedDatePickerWidget(
            attrs={"placeholder": "Pick a date"}
        )
        html = widget.render("test_field", None)
        self.assertIn('placeholder="Pick a date"', html)

    def test_default_placeholder_datetime(self):
        """Default placeholder for datetime mode."""
        widget = AnimatedDatePickerWidget(enable_time=True)
        html = widget.render("test_field", None)
        self.assertIn("Select Date &amp; Time", html)

    def test_default_placeholder_date_only(self):
        """Default placeholder for date-only mode."""
        widget = AnimatedDatePickerWidget(enable_time=False)
        html = widget.render("test_field", None)
        self.assertIn("Select Date", html)

    def test_custom_icon_class(self):
        """Custom icon_class should appear in the icon element."""
        widget = AnimatedDatePickerWidget(icon_class="fa-clock")
        html = widget.render("test_field", None)
        self.assertIn("fa-clock", html)

    def test_icon_class_is_escaped(self):
        """Icon class should be escaped to prevent XSS."""
        widget = AnimatedDatePickerWidget(
            icon_class='"><script>alert(1)</script>'
        )
        html = widget.render("test_field", None)
        # The script tag should be escaped, not rendered as HTML
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_datetime_format_string(self):
        """DateTime mode should use the ISO datetime format."""
        widget = AnimatedDatePickerWidget(enable_time=True)
        self.assertEqual(widget.format, "%Y-%m-%dT%H:%M")

    def test_date_only_format_string(self):
        """Date-only mode should use the ISO date format."""
        widget = AnimatedDatePickerWidget(enable_time=False)
        self.assertEqual(widget.format, "%Y-%m-%d")

    def test_renders_value_when_provided(self):
        """When a value is provided, it should appear in the input."""
        widget = AnimatedDatePickerWidget(enable_time=True)
        html = widget.render("test_field", "2025-06-15T14:30")
        self.assertIn("2025-06-15T14:30", html)

    def test_renders_empty_when_no_value(self):
        """When no value is provided, the input should not have a value attr with content."""
        widget = AnimatedDatePickerWidget()
        html = widget.render("test_field", None)
        # Should not have value="something"
        self.assertNotIn('value="20', html)

    def test_input_name_attribute(self):
        """The rendered input must have the correct name attribute."""
        widget = AnimatedDatePickerWidget()
        html = widget.render("my_date_field", None)
        self.assertIn('name="my_date_field"', html)

    def test_html_structure_order(self):
        """The wrapper should contain icon span before the input."""
        widget = AnimatedDatePickerWidget()
        html = widget.render("test_field", None)
        icon_pos = html.find("input-date-icon")
        input_pos = html.find('name="test_field"')
        self.assertGreater(input_pos, icon_pos, "Icon should come before input in the HTML")
