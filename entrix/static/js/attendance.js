/**
 * TRANSACTIONS APP — Attendance Management Module JavaScript
 * Handles AJAX modal populating, real-time filters, CSV export, print, and alert dismissal.
 */

document.addEventListener("DOMContentLoaded", function () {
    // --- Initialize Bootstrap Modals ---
    var memberModalEl = document.getElementById("memberModal");
    var memberModal = memberModalEl ? new bootstrap.Modal(memberModalEl) : null;

    var expiredModalEl = document.getElementById("expiredMembersModal");
    var expiredModal = expiredModalEl ? new bootstrap.Modal(expiredModalEl) : null;

    var manualModalEl = document.getElementById("manualEntryModal");
    var manualModal = manualModalEl ? new bootstrap.Modal(manualModalEl) : null;

    // --- Open Expired Members Modal ---
    var btnOpenExpired = document.getElementById("btnOpenExpired");
    if (btnOpenExpired && expiredModal) {
        btnOpenExpired.addEventListener("click", function () {
            expiredModal.show();
        });
    }

    // --- Open Manual Entry Modal ---
    var btnOpenManual = document.getElementById("btnOpenManual");
    if (btnOpenManual && manualModal) {
        btnOpenManual.addEventListener("click", function () {
            manualModal.show();
        });
    }

    // --- View Member Details via AJAX ---
    document.querySelectorAll(".btn-view-member").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var memberId = btn.getAttribute("data-member-id");
            if (!memberId || !memberModal) return;

            // Fetch real-time member data first to prevent modal flickering and layout jumps
            fetch("?action=get_member_details&member_id=" + encodeURIComponent(memberId), {
                headers: {
                    "X-Requested-With": "XMLHttpRequest"
                }
            })
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                // Populate Identity Strip
                document.getElementById("modalMemberName").textContent = data.name;
                document.getElementById("modalMemberId").textContent = data.id;
                document.getElementById("modalMemberPhoto").src = data.photo_url;
                
                var statusBadge = document.getElementById("modalStatusBadge");
                if (data.status === "Active") {
                    statusBadge.className = "badge entrix-badge-vip ms-auto";
                    statusBadge.textContent = "Active Member";
                } else {
                    statusBadge.className = "badge bg-danger ms-auto";
                    statusBadge.textContent = "Membership Expired";
                }

                // Populate Basic Info
                document.getElementById("modalGender").textContent = data.gender;
                document.getElementById("modalBlood").textContent = data.blood_group;
                document.getElementById("modalMobile").textContent = data.mobile;
                document.getElementById("modalJoinDate").textContent = data.join_date;

                // Populate Health Info
                document.getElementById("modalHeight").textContent = data.height;
                document.getElementById("modalWeight").textContent = data.weight;
                document.getElementById("modalBMI").textContent = data.bmi;
                document.getElementById("modalGoal").textContent = data.fitness_goal;
                document.getElementById("modalMedical").textContent = data.medical_condition;

                // Populate Membership Info
                document.getElementById("modalPlanName").textContent = data.plan;
                document.getElementById("modalPlanStatus").textContent = data.status;
                document.getElementById("modalPlanStatus").className = data.status === "Active" ? "entrix-modal-grid-value text-success" : "entrix-modal-grid-value text-danger";
                var planExpiryEl = document.getElementById("modalPlanExpiry");
                if (planExpiryEl) {
                    planExpiryEl.textContent = data.expiry_date || "--";
                }
                if (document.getElementById("modalPlanAmount")) document.getElementById("modalPlanAmount").textContent = data.plan_amount ? "₹" + data.plan_amount : "--";
                if (document.getElementById("modalAmountPaid")) document.getElementById("modalAmountPaid").textContent = data.amount_paid ? "₹" + data.amount_paid : "--";
                if (document.getElementById("modalRemainingAmount")) document.getElementById("modalRemainingAmount").textContent = data.remaining_amount ? "₹" + data.remaining_amount : "--";
                document.getElementById("modalJoinedSince").textContent = data.joined_since;
                document.getElementById("modalTotalVisits").textContent = data.total_visits;
                document.getElementById("modalLastVisit").textContent = data.last_visit;

                // Populate Attendance Summary Pills
                document.getElementById("modalCheckinToday").textContent = data.checkin_today;
                document.getElementById("modalDurationInside").textContent = data.duration_inside;
                document.getElementById("modalMonthVisits").textContent = data.month_visits;
                document.getElementById("modalTotalAttendance").textContent = data.total_attendance;

                memberModal.show();
            })
            .catch(function (err) {
                console.error("Error fetching member details:", err);
                document.getElementById("modalMemberName").textContent = "Error loading member data.";
                memberModal.show();
            });
        });
    });

    // --- View Trainer Details via AJAX ---
    document.querySelectorAll(".btn-view-trainer").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var trainerId = btn.getAttribute("data-trainer-id");
            if (!trainerId || !memberModal) return;

            fetch("?action=get_trainer_details&trainer_id=" + encodeURIComponent(trainerId), {
                headers: {
                    "X-Requested-With": "XMLHttpRequest"
                }
            })
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                document.getElementById("modalMemberName").textContent = data.name;
                document.getElementById("modalMemberId").textContent = data.id;
                document.getElementById("modalMemberPhoto").src = data.photo_url;

                var statusBadge = document.getElementById("modalStatusBadge");
                if (data.status === "Working" || data.status === "working") {
                    statusBadge.className = "badge bg-success ms-auto";
                    statusBadge.textContent = "Working Staff";
                } else {
                    statusBadge.className = "badge bg-warning text-dark ms-auto";
                    statusBadge.textContent = data.status;
                }

                document.getElementById("modalGender").textContent = data.gender;
                document.getElementById("modalBlood").textContent = data.blood_group;
                document.getElementById("modalMobile").textContent = data.mobile;
                document.getElementById("modalJoinDate").textContent = data.join_date;

                document.getElementById("modalHeight").textContent = data.height;
                document.getElementById("modalWeight").textContent = data.weight;
                document.getElementById("modalBMI").textContent = data.bmi;
                document.getElementById("modalGoal").textContent = data.fitness_goal;
                document.getElementById("modalMedical").textContent = data.medical_condition;

                document.getElementById("modalPlanName").textContent = data.plan;
                document.getElementById("modalPlanStatus").textContent = data.status;
                document.getElementById("modalPlanStatus").className = "entrix-modal-grid-value text-success";
                var planExpiryEl = document.getElementById("modalPlanExpiry");
                if (planExpiryEl) {
                    planExpiryEl.textContent = data.expiry_date || "--";
                }
                if (document.getElementById("modalPlanAmount")) document.getElementById("modalPlanAmount").textContent = data.plan_amount ? "₹" + data.plan_amount : "--";
                if (document.getElementById("modalAmountPaid")) document.getElementById("modalAmountPaid").textContent = data.amount_paid ? "₹" + data.amount_paid : "--";
                if (document.getElementById("modalRemainingAmount")) document.getElementById("modalRemainingAmount").textContent = data.remaining_amount ? "₹" + data.remaining_amount : "--";
                document.getElementById("modalJoinedSince").textContent = data.joined_since;
                document.getElementById("modalTotalVisits").textContent = data.total_visits;
                document.getElementById("modalLastVisit").textContent = data.last_visit;

                document.getElementById("modalCheckinToday").textContent = data.checkin_today;
                document.getElementById("modalDurationInside").textContent = data.duration_inside;
                document.getElementById("modalMonthVisits").textContent = data.month_visits;
                document.getElementById("modalTotalAttendance").textContent = data.total_attendance;

                memberModal.show();
            })
            .catch(function (err) {
                console.error("Error fetching trainer details:", err);
                document.getElementById("modalMemberName").textContent = "Error loading trainer data.";
                memberModal.show();
            });
        });
    });

    // --- Alert Banner Dismissal ---
    document.querySelectorAll(".btn-dismiss-alert").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var banner = btn.closest(".entrix-alert-banner");
            if (banner) {
                banner.style.opacity = "0";
                banner.style.transform = "translateY(-10px)";
                setTimeout(function () {
                    banner.remove();
                }, 300);
            }
        });
    });

    // --- View Member Details from Expired Modal ---
    document.querySelectorAll(".btn-view-expired-member").forEach(function (btn) {
        btn.addEventListener("click", function () {
            if (expiredModal) {
                expiredModal.hide();
            }
            var memberId = btn.getAttribute("data-member-id");
            if (!memberId) return;
            var targetBtn = document.querySelector(`.btn-view-member[data-member-id="${memberId}"]`);
            if (targetBtn) {
                targetBtn.click();
            } else {
                fetch("?action=get_member_details&member_id=" + encodeURIComponent(memberId), {
                    headers: { "X-Requested-With": "XMLHttpRequest" }
                })
                .then(function (response) { return response.json(); })
                .then(function (data) {
                    if (memberModal) {
                        document.getElementById("modalMemberName").textContent = data.name;
                        document.getElementById("modalMemberId").textContent = data.id;
                        document.getElementById("modalMemberPhoto").src = data.photo_url;
                        var statusBadge = document.getElementById("modalStatusBadge");
                        statusBadge.className = "badge bg-danger ms-auto";
                        statusBadge.textContent = "Membership Expired";
                        document.getElementById("modalGender").textContent = data.gender;
                        document.getElementById("modalBlood").textContent = data.blood_group;
                        document.getElementById("modalMobile").textContent = data.mobile;
                        document.getElementById("modalJoinDate").textContent = data.join_date;
                        document.getElementById("modalHeight").textContent = data.height;
                        document.getElementById("modalWeight").textContent = data.weight;
                        document.getElementById("modalBMI").textContent = data.bmi;
                        document.getElementById("modalGoal").textContent = data.fitness_goal;
                        document.getElementById("modalMedical").textContent = data.medical_condition;
                        document.getElementById("modalPlanName").textContent = data.plan;
                        document.getElementById("modalPlanStatus").textContent = data.status;
                        document.getElementById("modalPlanStatus").className = "entrix-modal-grid-value text-danger";
                        var planExpiryEl = document.getElementById("modalPlanExpiry");
                        if (planExpiryEl) planExpiryEl.textContent = data.expiry_date || "--";
                        if (document.getElementById("modalPlanAmount")) document.getElementById("modalPlanAmount").textContent = data.plan_amount ? "₹" + data.plan_amount : "--";
                        if (document.getElementById("modalAmountPaid")) document.getElementById("modalAmountPaid").textContent = data.amount_paid ? "₹" + data.amount_paid : "--";
                        if (document.getElementById("modalRemainingAmount")) document.getElementById("modalRemainingAmount").textContent = data.remaining_amount ? "₹" + data.remaining_amount : "--";
                        document.getElementById("modalJoinedSince").textContent = data.joined_since;
                        document.getElementById("modalTotalVisits").textContent = data.total_visits;
                        document.getElementById("modalLastVisit").textContent = data.last_visit;
                        document.getElementById("modalCheckinToday").textContent = data.checkin_today;
                        document.getElementById("modalDurationInside").textContent = data.duration_inside;
                        document.getElementById("modalMonthVisits").textContent = data.month_visits;
                        document.getElementById("modalTotalAttendance").textContent = data.total_attendance;
                        memberModal.show();
                    }
                });
            }
        });
    });


});

