/**
 * REPORTS APP — Attendance Report Module JavaScript
 * Handles preset date range toggling, accordion expand/collapse, AJAX member/trainer detail modals, and deletion confirmation.
 */

document.addEventListener("DOMContentLoaded", function () {
    // --- Initialize Bootstrap Modals ---
    var reportModalEl = document.getElementById("reportDetailModal");
    var reportModal = reportModalEl ? new bootstrap.Modal(reportModalEl) : null;

    var deleteModalEl = document.getElementById("deleteConfirmModal");
    var deleteModal = deleteModalEl ? new bootstrap.Modal(deleteModalEl) : null;

    // --- Date Preset Toggling ---
    var presetSelect = document.getElementById("id_date_preset");
    var customContainers = document.querySelectorAll(".custom-date-container");

    function toggleCustomDates() {
        if (!presetSelect) return;
        var isCustom = presetSelect.value === "custom";
        customContainers.forEach(function (container) {
            if (isCustom) {
                container.classList.remove("d-none");
            } else {
                container.classList.add("d-none");
            }
        });
    }

    if (presetSelect) {
        presetSelect.addEventListener("change", toggleCustomDates);
        toggleCustomDates();
    }

    // --- Accordion Expand / Collapse All ---
    var btnExpandAll = document.getElementById("btnExpandAll");
    var btnCollapseAll = document.getElementById("btnCollapseAll");

    if (btnExpandAll) {
        btnExpandAll.addEventListener("click", function () {
            document.querySelectorAll("#attendanceAccordion .accordion-collapse").forEach(function (el) {
                var bsCollapse = bootstrap.Collapse.getOrCreateInstance(el, { toggle: false });
                bsCollapse.show();
            });
            document.querySelectorAll("#attendanceAccordion .accordion-button").forEach(function (btn) {
                btn.classList.remove("collapsed");
                btn.setAttribute("aria-expanded", "true");
            });
        });
    }

    if (btnCollapseAll) {
        btnCollapseAll.addEventListener("click", function () {
            document.querySelectorAll("#attendanceAccordion .accordion-collapse").forEach(function (el) {
                var bsCollapse = bootstrap.Collapse.getOrCreateInstance(el, { toggle: false });
                bsCollapse.hide();
            });
            document.querySelectorAll("#attendanceAccordion .accordion-button").forEach(function (btn) {
                btn.classList.add("collapsed");
                btn.setAttribute("aria-expanded", "false");
            });
        });
    }

    // --- View Member Details via AJAX ---
    document.querySelectorAll(".btn-view-member-report").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var memberId = btn.getAttribute("data-member-id");
            if (!memberId || !reportModal) return;

            // Set temporary loading state
            document.getElementById("reportModalName").textContent = "Loading...";
            document.getElementById("reportModalId").innerHTML = '<i class="bi bi-person-vcard me-1"></i>' + memberId;
            document.getElementById("reportModalStatusBadge").textContent = "--";

            // Fetch member data
            fetch(window.location.pathname + "?action=get_member_details&member_id=" + encodeURIComponent(memberId), {
                headers: {
                    "X-Requested-With": "XMLHttpRequest"
                }
            })
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                if (data.error) {
                    document.getElementById("reportModalName").textContent = "Error";
                    return;
                }

                // Populate Identity Strip
                document.getElementById("reportModalName").textContent = data.name;
                document.getElementById("reportModalId").innerHTML = '<i class="bi bi-person-vcard me-1"></i>' + data.id;
                var photoEl = document.getElementById("reportModalPhoto");
                if (photoEl && data.photo_url) photoEl.src = data.photo_url;

                var statusBadge = document.getElementById("reportModalStatusBadge");
                if (data.status === "Active") {
                    statusBadge.className = "badge entrix-badge-vip ms-auto";
                    statusBadge.textContent = "Active Member";
                } else {
                    statusBadge.className = "badge bg-danger ms-auto";
                    statusBadge.textContent = "Membership Expired";
                }

                // Populate Basic Info
                document.getElementById("reportModalGender").textContent = data.gender || "--";
                document.getElementById("reportModalBlood").textContent = data.blood_group || "--";
                document.getElementById("reportModalMobile").textContent = data.mobile || "--";
                document.getElementById("reportModalJoinDate").textContent = data.join_date || "--";

                // Populate Health Info
                document.getElementById("reportModalHeight").textContent = data.height || "--";
                document.getElementById("reportModalWeight").textContent = data.weight || "--";
                document.getElementById("reportModalBMI").textContent = data.bmi || "--";
                document.getElementById("reportModalGoal").textContent = data.fitness_goal || "--";
                document.getElementById("reportModalMedical").textContent = data.medical_condition || "--";

                // Populate Membership Info
                document.getElementById("reportModalPlanName").textContent = data.plan || "--";
                document.getElementById("reportModalPlanStatus").textContent = data.status || "--";
                document.getElementById("reportModalPlanStatus").className = data.status === "Active" ? "entrix-modal-grid-value text-success" : "entrix-modal-grid-value text-danger";
                var planExpiryEl = document.getElementById("reportModalPlanExpiry");
                if (planExpiryEl) {
                    planExpiryEl.textContent = data.expiry_date || "--";
                }
                if (document.getElementById("reportModalPlanAmount")) document.getElementById("reportModalPlanAmount").textContent = data.plan_amount ? "₹" + data.plan_amount : "--";
                if (document.getElementById("reportModalAmountPaid")) document.getElementById("reportModalAmountPaid").textContent = data.amount_paid ? "₹" + data.amount_paid : "--";
                if (document.getElementById("reportModalRemainingAmount")) document.getElementById("reportModalRemainingAmount").textContent = data.remaining_amount ? "₹" + data.remaining_amount : "--";
                document.getElementById("reportModalJoinedSince").textContent = data.joined_since || "--";
                document.getElementById("reportModalTotalVisits").textContent = data.total_visits || "--";
                document.getElementById("reportModalLastVisit").textContent = data.last_visit || "--";

                // Populate Attendance Summary Pills
                document.getElementById("reportModalCheckinToday").textContent = data.checkin_today || "--";
                document.getElementById("reportModalDurationInside").textContent = data.duration_inside || "--";
                document.getElementById("reportModalMonthVisits").textContent = data.month_visits || "--";
                document.getElementById("reportModalTotalAttendance").textContent = data.total_attendance || "--";

                reportModal.show();
            })
            .catch(function (err) {
                console.error("Error fetching member details:", err);
                document.getElementById("reportModalName").textContent = "Error loading member data.";
                reportModal.show();
            });
        });
    });

    // --- View Trainer Details via AJAX ---
    document.querySelectorAll(".btn-view-trainer-report").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var trainerId = btn.getAttribute("data-trainer-id");
            if (!trainerId || !reportModal) return;

            // Set temporary loading state
            document.getElementById("reportModalName").textContent = "Loading...";
            document.getElementById("reportModalId").innerHTML = '<i class="bi bi-person-vcard me-1"></i>' + trainerId;
            document.getElementById("reportModalStatusBadge").textContent = "--";

            fetch(window.location.pathname + "?action=get_trainer_details&trainer_id=" + encodeURIComponent(trainerId), {
                headers: {
                    "X-Requested-With": "XMLHttpRequest"
                }
            })
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                if (data.error) {
                    document.getElementById("reportModalName").textContent = "Error";
                    return;
                }

                // Populate Identity Strip
                document.getElementById("reportModalName").textContent = data.name;
                document.getElementById("reportModalId").innerHTML = '<i class="bi bi-person-vcard me-1"></i>' + data.id;
                var photoEl = document.getElementById("reportModalPhoto");
                if (photoEl && data.photo_url) photoEl.src = data.photo_url;

                var statusBadge = document.getElementById("reportModalStatusBadge");
                if (data.status === "Working" || data.status === "working") {
                    statusBadge.className = "badge bg-success ms-auto";
                    statusBadge.textContent = "Working Staff";
                } else {
                    statusBadge.className = "badge bg-warning text-dark ms-auto";
                    statusBadge.textContent = data.status || "--";
                }

                // Populate Basic Info
                document.getElementById("reportModalGender").textContent = data.gender || "--";
                document.getElementById("reportModalBlood").textContent = data.blood_group || "--";
                document.getElementById("reportModalMobile").textContent = data.mobile || "--";
                document.getElementById("reportModalJoinDate").textContent = data.join_date || "--";

                // Populate Health Info
                document.getElementById("reportModalHeight").textContent = data.height || "--";
                document.getElementById("reportModalWeight").textContent = data.weight || "--";
                document.getElementById("reportModalBMI").textContent = data.bmi || "--";
                document.getElementById("reportModalGoal").textContent = data.fitness_goal || "--";
                document.getElementById("reportModalMedical").textContent = data.medical_condition || "--";

                // Populate Membership Info
                document.getElementById("reportModalPlanName").textContent = data.plan || "--";
                document.getElementById("reportModalPlanStatus").textContent = data.status || "--";
                document.getElementById("reportModalPlanStatus").className = "entrix-modal-grid-value text-success";
                var planExpiryEl = document.getElementById("reportModalPlanExpiry");
                if (planExpiryEl) {
                    planExpiryEl.textContent = data.expiry_date || "--";
                }
                if (document.getElementById("reportModalPlanAmount")) document.getElementById("reportModalPlanAmount").textContent = data.plan_amount ? "₹" + data.plan_amount : "--";
                if (document.getElementById("reportModalAmountPaid")) document.getElementById("reportModalAmountPaid").textContent = data.amount_paid ? "₹" + data.amount_paid : "--";
                if (document.getElementById("reportModalRemainingAmount")) document.getElementById("reportModalRemainingAmount").textContent = data.remaining_amount ? "₹" + data.remaining_amount : "--";
                document.getElementById("reportModalJoinedSince").textContent = data.joined_since || "--";
                document.getElementById("reportModalTotalVisits").textContent = data.total_visits || "--";
                document.getElementById("reportModalLastVisit").textContent = data.last_visit || "--";

                // Populate Attendance Summary Pills
                document.getElementById("reportModalCheckinToday").textContent = data.checkin_today || "--";
                document.getElementById("reportModalDurationInside").textContent = data.duration_inside || "--";
                document.getElementById("reportModalMonthVisits").textContent = data.month_visits || "--";
                document.getElementById("reportModalTotalAttendance").textContent = data.total_attendance || "--";

                reportModal.show();
            })
            .catch(function (err) {
                console.error("Error fetching trainer details:", err);
                document.getElementById("reportModalName").textContent = "Error loading trainer data.";
                reportModal.show();
            });
        });
    });

    // --- Delete Member Report Confirmation ---
    document.querySelectorAll(".btn-delete-member-report").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var attId = btn.getAttribute("data-att-id");
            var memberName = btn.getAttribute("data-member-name");
            var attDate = btn.getAttribute("data-att-date");
            if (!attId || !deleteModal) return;

            document.getElementById("deleteActionInput").value = "delete_attendance";
            document.getElementById("deleteAttendanceIdInput").value = attId;
            document.getElementById("deleteConfirmText").textContent = "Are you sure you want to delete the check-in record for member \"" + memberName + "\" on " + attDate + "?";

            deleteModal.show();
        });
    });

    // --- Delete Trainer Report Confirmation ---
    document.querySelectorAll(".btn-delete-trainer-report").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var attId = btn.getAttribute("data-att-id");
            var trainerName = btn.getAttribute("data-trainer-name");
            var attDate = btn.getAttribute("data-att-date");
            if (!attId || !deleteModal) return;

            document.getElementById("deleteActionInput").value = "delete_trainer_attendance";
            document.getElementById("deleteAttendanceIdInput").value = attId;
            document.getElementById("deleteConfirmText").textContent = "Are you sure you want to delete the check-in record for trainer \"" + trainerName + "\" on " + attDate + "?";

            deleteModal.show();
        });
    });
});
