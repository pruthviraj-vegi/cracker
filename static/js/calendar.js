/**
 * Custom Calendar Component
 * Theme-compatible calendar for date selection
 */

class CalendarControl {
    constructor(container, options = {}) {
        this.container = typeof container === 'string'
            ? document.querySelector(container)
            : container;
        this.options = {
            onDateSelect: options.onDateSelect || null,
            initialDate: options.initialDate || new Date(),
            ...options
        };
        this.calendar = new Date(this.options.initialDate);
        this.localDate = new Date();
        this.prevMonthLastDate = null;
        this.calWeekDays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
        this.calMonthName = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
        ];

        if (this.container) {
            this.init();
        }
    }

    daysInMonth(month, year) {
        // month parameter is 1-12 (not 0-11)
        // Convert to 0-11 for JavaScript Date, then use 0 as day to get last day of previous month
        return new Date(year, month, 0).getDate();
    }

    firstDay() {
        return new Date(this.calendar.getFullYear(), this.calendar.getMonth(), 1);
    }

    lastDay() {
        return new Date(this.calendar.getFullYear(), this.calendar.getMonth() + 1, 0);
    }

    firstDayNumber() {
        return this.firstDay().getDay() + 1;
    }

    lastDayNumber() {
        return this.lastDay().getDay() + 1;
    }

    getPreviousMonthLastDate() {
        let lastDate = new Date(
            this.calendar.getFullYear(),
            this.calendar.getMonth(),
            0
        ).getDate();
        return lastDate;
    }

    navigateToPreviousMonth() {
        const currentYear = this.calendar.getFullYear();
        const currentMonth = this.calendar.getMonth();

        // Create a new Date object to avoid mutation issues
        let newYear = currentYear;
        let newMonth = currentMonth - 1;

        if (newMonth < 0) {
            newMonth = 11;
            newYear = currentYear - 1;
        }

        // Create fresh Date object with day 1 to avoid overflow
        this.calendar = new Date(newYear, newMonth, 1);

        this.attachEventsOnNextPrev();
    }

    navigateToNextMonth() {
        const currentYear = this.calendar.getFullYear();
        const currentMonth = this.calendar.getMonth();

        // Create a new Date object to avoid mutation issues
        let newYear = currentYear;
        let newMonth = currentMonth + 1;

        if (newMonth > 11) {
            newMonth = 0;
            newYear = currentYear + 1;
        }

        // Create fresh Date object with day 1 to avoid overflow
        this.calendar = new Date(newYear, newMonth, 1);

        this.attachEventsOnNextPrev();
    }

    navigateToCurrentMonth() {
        let currentMonth = this.localDate.getMonth();
        let currentYear = this.localDate.getFullYear();
        // Create fresh Date object to avoid mutation issues
        this.calendar = new Date(currentYear, currentMonth, 1);
        this.attachEventsOnNextPrev();
    }

    _getCalendarElement() {
        // If container itself is the calendar, return it
        if (this.container.classList.contains('calendar')) {
            return this.container;
        }
        // Otherwise, look for .calendar inside container
        return this.container.querySelector(".calendar");
    }

    displayYear() {
        const calendarEl = this._getCalendarElement();
        let yearLabel = calendarEl ? calendarEl.querySelector(".calendar-year-label") : null;
        if (yearLabel) {
            yearLabel.innerHTML = this.calendar.getFullYear();
        }
    }

    displayMonth() {
        const calendarEl = this._getCalendarElement();
        let monthLabel = calendarEl ? calendarEl.querySelector(".calendar-month-label") : null;
        if (monthLabel) {
            monthLabel.innerHTML = this.calMonthName[this.calendar.getMonth()];
        }
    }

    selectDate(e) {
        e.preventDefault();
        const selectedDate = e.target.textContent;
        const selectedMonth = this.calendar.getMonth();
        const selectedYear = this.calendar.getFullYear();

        // Format date as YYYY-MM-DD for date inputs
        const date = new Date(selectedYear, selectedMonth, parseInt(selectedDate));
        const formattedDate = date.toISOString().split('T')[0];

        if (this.options.onDateSelect) {
            this.options.onDateSelect(formattedDate, date);
        }

        // Dispatch custom event
        const event = new CustomEvent('dateSelected', {
            detail: { date: formattedDate, dateObj: date }
        });
        this.container.dispatchEvent(event);
    }

    plotSelectors() {
        const calendarEl = this._getCalendarElement();
        if (!calendarEl) {
            console.error('Calendar element not found for plotSelectors');
            return;
        }

        calendarEl.innerHTML = `<div class="calendar-inner">
            <div class="calendar-controls">
                <div class="calendar-prev">
                    <a href="#" aria-label="Previous Month">
                        <i class="fa-solid fa-chevron-left"></i>
                    </a>
                </div>
                <div class="calendar-year-month">
                    <div class="calendar-month-label"></div>
                    <div>•</div>
                    <div class="calendar-year-label"></div>
                </div>
                <div class="calendar-next">
                    <a href="#" aria-label="Next Month">
                        <i class="fa-solid fa-chevron-right"></i>
                    </a>
                </div>
            </div>
            <div class="calendar-today-date">
                Today: ${this.calWeekDays[this.localDate.getDay()]}, 
                ${this.localDate.getDate()} 
                ${this.calMonthName[this.localDate.getMonth()]} 
                ${this.localDate.getFullYear()}
            </div>
            <div class="calendar-body"></div>
        </div>`;
    }

    plotDayNames() {
        const calendarEl = this._getCalendarElement();
        const calendarBody = calendarEl ? calendarEl.querySelector(".calendar-body") : null;
        if (!calendarBody) {
            console.error('Calendar body not found');
            return;
        }

        for (let i = 0; i < this.calWeekDays.length; i++) {
            calendarBody.innerHTML += `<div>${this.calWeekDays[i]}</div>`;
        }
    }

    plotDates() {
        const calendarEl = this._getCalendarElement();
        const calendarBody = calendarEl ? calendarEl.querySelector(".calendar-body") : null;
        if (!calendarBody) {
            console.error('Calendar body not found in plotDates');
            return;
        }

        calendarBody.innerHTML = "";
        this.plotDayNames();
        this.displayMonth();
        this.displayYear();

        let prevDateCount = 0;
        this.prevMonthLastDate = this.getPreviousMonthLastDate();
        let prevMonthDatesArray = [];
        let calendarDays = this.daysInMonth(
            this.calendar.getMonth() + 1,
            this.calendar.getFullYear()
        );
        let firstDayNum = this.firstDayNumber(); // 1-7 (1=Sun, 7=Sat)

        // Step 1: Fill previous month dates (positions before first day of current month)
        for (let i = 0; i < firstDayNum - 1; i++) {
            prevDateCount++;
            calendarBody.innerHTML += `<div class="prev-dates"></div>`;
            prevMonthDatesArray.push(this.prevMonthLastDate--);
        }

        // Step 2: Fill current month dates
        for (let dayOfMonth = 1; dayOfMonth <= calendarDays; dayOfMonth++) {
            calendarBody.innerHTML += `<div class="number-item" data-num=${dayOfMonth}>
                <a class="dateNumber" href="#">${dayOfMonth}</a>
            </div>`;
        }

        // Step 3: Calculate remaining cells and fill with next month dates (handled by plotNextMonthDates)

        this.highlightToday();
        this.plotPrevMonthDates(prevMonthDatesArray);
        this.plotNextMonthDates();
    }

    attachEvents() {
        const calendarEl = this._getCalendarElement();
        if (!calendarEl) {
            console.error('Calendar element not found for attachEvents');
            return;
        }

        // Remove old event listeners if they exist
        if (this._prevBtnHandler) {
            const prevBtn = calendarEl.querySelector(".calendar-prev a");
            if (prevBtn) {
                prevBtn.removeEventListener("click", this._prevBtnHandler);
            }
        }
        if (this._nextBtnHandler) {
            const nextBtn = calendarEl.querySelector(".calendar-next a");
            if (nextBtn) {
                nextBtn.removeEventListener("click", this._nextBtnHandler);
            }
        }
        if (this._todayDateHandler) {
            const todayDate = calendarEl.querySelector(".calendar-today-date");
            if (todayDate) {
                todayDate.removeEventListener("click", this._todayDateHandler);
            }
        }

        // Create new handler functions and store references
        this._prevBtnHandler = (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.navigateToPreviousMonth();
        };

        this._nextBtnHandler = (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.navigateToNextMonth();
        };

        this._todayDateHandler = (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.navigateToCurrentMonth();
        };

        const prevBtn = calendarEl.querySelector(".calendar-prev a");
        const nextBtn = calendarEl.querySelector(".calendar-next a");
        const todayDate = calendarEl.querySelector(".calendar-today-date");
        const dateNumbers = calendarEl.querySelectorAll(".dateNumber");

        if (prevBtn) {
            prevBtn.addEventListener("click", this._prevBtnHandler);
        }

        if (nextBtn) {
            nextBtn.addEventListener("click", this._nextBtnHandler);
        }

        if (todayDate) {
            todayDate.addEventListener("click", this._todayDateHandler);
        }

        dateNumbers.forEach(dateNumber => {
            // Remove old listener if exists (using data attribute to track)
            if (dateNumber.dataset.hasListener === 'true') {
                dateNumber.removeEventListener("click", dateNumber._dateHandler);
            }
            dateNumber._dateHandler = (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.selectDate(e);
            };
            dateNumber.addEventListener("click", dateNumber._dateHandler);
            dateNumber.dataset.hasListener = 'true';
        });
    }

    highlightToday() {
        const calendarEl = this._getCalendarElement();
        if (!calendarEl) return;

        let currentMonth = this.localDate.getMonth() + 1;
        let changedMonth = this.calendar.getMonth() + 1;
        let currentYear = this.localDate.getFullYear();
        let changedYear = this.calendar.getFullYear();
        let currentDay = this.localDate.getDate();

        if (
            currentYear === changedYear &&
            currentMonth === changedMonth
        ) {
            const numberItems = calendarEl.querySelectorAll(".number-item");
            // Find the item that matches today's date
            numberItems.forEach((item, index) => {
                const dateLink = item.querySelector('.dateNumber');
                if (dateLink && parseInt(dateLink.textContent) === currentDay) {
                    item.classList.add("calendar-today");
                }
            });
        }
    }

    plotPrevMonthDates(dates) {
        const calendarEl = this._getCalendarElement();
        if (!calendarEl) return;

        dates.reverse();
        const prevDates = calendarEl.querySelectorAll(".prev-dates");
        for (let i = 0; i < dates.length && i < prevDates.length; i++) {
            prevDates[i].textContent = dates[i];
            prevDates[i].classList.add("prev-dates");
        }
    }

    plotNextMonthDates() {
        const calendarEl = this._getCalendarElement();
        const calendarBody = calendarEl ? calendarEl.querySelector('.calendar-body') : null;
        if (!calendarBody) return;

        let childElemCount = calendarBody.childElementCount;

        // 7 lines
        if (childElemCount > 42) {
            let diff = 49 - childElemCount;
            this.loopThroughNextDays(diff);
        }
        // 6 lines
        if (childElemCount > 35 && childElemCount <= 42) {
            let diff = 42 - childElemCount;
            this.loopThroughNextDays(diff);
        }
    }

    loopThroughNextDays(count) {
        const calendarBody = this.container.querySelector('.calendar-body');
        if (!calendarBody) return;

        if (count > 0) {
            // Calculate next month's first date
            const nextMonth = this.calendar.getMonth() + 1;
            const nextYear = this.calendar.getFullYear();
            if (nextMonth === 12) {
                // December -> January of next year
                const nextMonthDate = new Date(nextYear + 1, 0, 1);
                for (let i = 1; i <= count; i++) {
                    calendarBody.innerHTML += `<div class="next-dates">${i}</div>`;
                }
            } else {
                const nextMonthDate = new Date(nextYear, nextMonth, 1);
                for (let i = 1; i <= count; i++) {
                    calendarBody.innerHTML += `<div class="next-dates">${i}</div>`;
                }
            }
        }
    }

    attachEventsOnNextPrev() {
        this.plotDates();
        this.attachEvents();
    }

    init() {
        this.plotSelectors();
        this.plotDates();
        this.attachEvents();
    }

    show() {
        const calendarEl = this._getCalendarElement();
        if (calendarEl) {
            calendarEl.classList.add("show");

            // Adjust position after a brief delay to ensure layout is calculated
            setTimeout(() => {
                this._adjustPosition(calendarEl);
            }, 10);
        } else {
            console.error('Calendar element not found in container:', this.container);
        }
    }

    _adjustPosition(calendarEl) {
        // Reset positioning
        calendarEl.style.top = '';
        calendarEl.style.bottom = '';
        calendarEl.style.marginTop = '';
        calendarEl.style.marginBottom = '';

        // Check if calendar would overflow viewport
        const rect = calendarEl.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        // Check right overflow
        if (rect.right > viewportWidth - 10) {
            calendarEl.classList.add('align-left');
        } else {
            calendarEl.classList.remove('align-left');
        }

        // Check bottom overflow - adjust if needed
        if (rect.bottom > viewportHeight - 10) {
            // Position above input instead
            const wrapper = calendarEl.closest('.calendar-wrapper');
            if (wrapper) {
                calendarEl.style.top = 'auto';
                calendarEl.style.bottom = '100%';
                calendarEl.style.marginTop = '0';
                calendarEl.style.marginBottom = '0.5rem';
            }
        }
    }

    hide() {
        const calendarEl = this._getCalendarElement();
        if (calendarEl) {
            calendarEl.classList.remove("show");
            // Reset positioning for next show
            calendarEl.style.top = '';
            calendarEl.style.bottom = '';
            calendarEl.style.marginTop = '';
            calendarEl.style.marginBottom = '';
        }
    }

    toggle() {
        const calendarEl = this._getCalendarElement();
        if (calendarEl) {
            calendarEl.classList.toggle("show");
        }
    }
}

/**
 * Initialize calendar for date inputs
 * Usage: initDateInputCalendar('#myDateInput')
 */
function initDateInputCalendar(inputSelector, options = {}) {
    const input = typeof inputSelector === 'string'
        ? document.querySelector(inputSelector)
        : inputSelector;

    if (!input) return null;

    // Check if already wrapped
    if (input.parentNode && input.parentNode.classList.contains('calendar-wrapper')) {
        // Already initialized, return existing calendar
        return input.parentNode._calendarInstance || null;
    }

    // Create calendar wrapper
    const wrapper = document.createElement('div');
    wrapper.className = 'calendar-wrapper';
    const parent = input.parentNode;
    parent.insertBefore(wrapper, input);
    wrapper.appendChild(input);

    // Create calendar container
    const calendarContainer = document.createElement('div');
    calendarContainer.className = 'calendar';
    wrapper.appendChild(calendarContainer);

    // Initialize calendar
    const calendar = new CalendarControl(calendarContainer, {
        onDateSelect: (formattedDate, dateObj) => {
            // Format date as dd-mm-yyyy for display
            const day = String(dateObj.getDate()).padStart(2, '0');
            const month = String(dateObj.getMonth() + 1).padStart(2, '0');
            const year = dateObj.getFullYear();
            const displayDate = `${day}-${month}-${year}`;

            input.value = displayDate;
            // Store the ISO date in a data attribute for form submission
            input.setAttribute('data-iso-date', formattedDate);
            calendar.hide();
            if (options.onSelect) {
                options.onSelect(formattedDate, dateObj);
            }
        },
        ...options
    });

    // Show custom calendar on input click/focus
    input.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        calendar.show();
    });

    input.addEventListener('focus', (e) => {
        e.preventDefault();
        calendar.show();
    });

    // Also add mousedown to ensure it works
    input.addEventListener('mousedown', (e) => {
        e.preventDefault();
        calendar.show();
    });

    // Close calendar when clicking outside
    const closeHandler = (e) => {
        if (!wrapper.contains(e.target)) {
            calendar.hide();
        }
    };
    document.addEventListener('click', closeHandler);

    // Store calendar instance on wrapper for reuse
    wrapper._calendarInstance = calendar;
    wrapper._closeHandler = closeHandler;

    return calendar;
}

// Auto-initialize calendars on page load
document.addEventListener('DOMContentLoaded', function () {
    // Initialize calendars for inputs with data-calendar attribute
    document.querySelectorAll('input[data-calendar]').forEach(input => {
        initDateInputCalendar(input);
    });
});

