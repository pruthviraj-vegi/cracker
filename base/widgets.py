"""
Custom form widgets for the My_Billing project.

Provides ``AnimatedDatePickerWidget`` — a drop-in replacement for Django's
DateInput / DateTimeInput that automatically renders the animated datepicker
wrapper, icon, and correct CSS classes.  Templates only need ``{{ form.field }}``
with no manual wrapper markup.
"""

from django import forms
from django.utils.html import format_html


class AnimatedDatePickerWidget(forms.DateTimeInput):
    """
    Renders a date/datetime ``<input>`` wrapped in the animated datepicker
    component (``input-date-wrapper`` div + icon badge + styled input).

    The widget sets all required HTML attributes (``type="text"``,
    ``readonly``, ``autocomplete="off"``, CSS classes, ``data-*`` flags)
    so that the global auto-init in ``animated-datepicker.js`` picks it up
    on ``DOMContentLoaded`` automatically.

    Args:
        enable_time: If ``True`` (default), renders a date + time picker.
                     If ``False``, renders a date-only picker.
        icon_class:  FontAwesome icon class for the calendar icon badge.
                     Defaults to ``'fa-calendar-days'``.
        attrs:       Additional HTML attributes merged onto the ``<input>``.

    Usage::

        class MyForm(forms.ModelForm):
            class Meta:
                widgets = {
                    "invoice_date": AnimatedDatePickerWidget(
                        enable_time=True,
                        icon_class="fa-calendar-days",
                    ),
                    "start_date": AnimatedDatePickerWidget(enable_time=False),
                }
    """

    def __init__(self, attrs=None, enable_time=True, icon_class="fa-calendar-days"):
        self.enable_time = enable_time
        self.icon_class = icon_class

        # Format string: datetime or date-only
        fmt = "%Y-%m-%dT%H:%M" if enable_time else "%Y-%m-%d"

        default_attrs = {
            "type": "text",
            "class": "form-input form-date-input",
            "autocomplete": "off",
            "readonly": True,
            "style": "cursor: pointer;",
            "data-datepicker-time": "true" if enable_time else "false",
            "placeholder": (
                "Select Date & Time" if enable_time else "Select Date"
            ),
        }

        if attrs:
            default_attrs.update(attrs)

        super().__init__(attrs=default_attrs, format=fmt)

    def render(self, name, value, attrs=None, renderer=None):
        """Render the input wrapped in the animated datepicker wrapper HTML."""
        input_html = super().render(
            name, value, attrs=attrs, renderer=renderer
        )

        return format_html(
            '<div class="input-date-wrapper">'
            '<span class="input-date-icon">'
            '<i class="fa-solid {}"></i>'
            "</span>"
            "{}"
            "</div>",
            self.icon_class,
            input_html,
        )
