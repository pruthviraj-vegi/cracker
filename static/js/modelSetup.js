function setupModal(id_input, name, model_link, form_id, create_url) { // 1. Add "Add" link to the label
    var idModelSelect = document.getElementById(id_input);
    if (!idModelSelect) {
        console.error('Select field not found:', id_input);
        return;
    }

    var formInnerDiv = idModelSelect.closest(".form-group");
    if (!formInnerDiv) {
        console.error('Form group not found for:', id_input);
        return;
    }

    var label = formInnerDiv.querySelector("label");
    if (!label) {
        console.error('Label not found for:', id_input);
        return;
    }

    var link = document.createElement("a");
    link.textContent = " - Add " + name;
    link.href = "#";
    link.setAttribute("data-bs-toggle", "modal");
    link.setAttribute("data-bs-target", "#" + model_link);

    label.appendChild(link);

    // Add event listener to focus first input when modal opens
    var modal = document.getElementById(model_link);
    modal.addEventListener('shown.bs.modal', function () {
        var firstInput = modal.querySelector('input[type="text"], input[type="email"], input[type="number"], textarea');
        if (firstInput)
            firstInput.focus();

    });

    modal.addEventListener('hide.bs.modal', function () {
        if (document.activeElement)
            document.activeElement.blur();

    });

    // 2. Setup AJAX form submission
    $(form_id).submit(function (e) {
        e.preventDefault();
        var form = $(this).closest("form");
        var formData = form.serialize();

        $.ajax({
            url: create_url,
            method: "POST",
            data: formData,
            success: function (response) {
                if (response.success) {
                    var item = response.data;
                    if (item && item.id && item.name) {
                        var selectElement = document.getElementById(id_input);
                        if (selectElement) {
                            var newOption = new Option(item.name, item.id, true, true);
                            selectElement.appendChild(newOption);
                            selectElement.value = item.id;
                            // Ensure it's selected

                            // Update Select2 instance if it exists
                            if ($(selectElement).hasClass('select2-hidden-accessible')) {
                                $(selectElement).trigger('change.select2');
                            } else {
                                selectElement.dispatchEvent(new Event('change', { bubbles: true }));
                            }
                        } else {
                            console.error('Select element not found:', id_input);
                        }
                    } else {
                        console.error('Invalid item data:', item);
                    }

                    // Reset the form
                    form[0].reset();

                    // Close modal properly
                    var modalElement = form.closest(".modal");
                    if (modalElement) {
                        var modalInstance = bootstrap.Modal.getInstance(modalElement);
                        if (modalInstance) {
                            modalInstance.hide();
                        }
                    }

                    showNotification('Created successfully!', 'success');
                } else {
                    console.error('AJAX Error:', response.message);
                    showNotification(response.message || 'Failed to create', 'error');
                }
            },
            error: function (xhr, errmsg, err) {
                console.error('AJAX request failed:', errmsg, err);
                showNotification("Failed to create item", 'error');
            }
        });
    });
}
