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

    // Toggle the shared detail modal between "member" and "trainer" layouts.
    // Member-only cards (Health Info, Membership Info) are hidden for trainers,
    // and the trainer-only Employment Info card is shown instead — so the
    // Trainer View popup never shows member fields like Plan Details/Amount.
    function setModalRole(role) {
        var isTrainer = role === "trainer";
        document.querySelectorAll(".modal-member-only").forEach(function (el) {
            el.classList.toggle("d-none", isTrainer);
        });
        document.querySelectorAll(".modal-trainer-only").forEach(function (el) {
            el.classList.toggle("d-none", !isTrainer);
        });
        var titleEl = document.getElementById("modalMainTitle");
        if (titleEl) {
            titleEl.innerHTML = isTrainer
                ? '<i class="bi bi-person-vcard-fill me-2"></i>Trainer Profile & Attendance Details'
                : '<i class="bi bi-person-badge-fill me-2"></i>Member Profile & Attendance Details';
        }
    }

    // --- Open Expired Members Modal ---
    var btnOpenExpired = document.getElementById("btnOpenExpired");
    if (btnOpenExpired && expiredModal) {
        btnOpenExpired.addEventListener("click", function () {
            expiredModal.show();
        });
    }

    // --- Manual Check-In Modal: search + paginated eligible-member list ---
    // Only active members with an active membership plan are returned by the
    // server; each row offers a Quick Check-In that reuses the existing
    // check_in POST action.
    var btnOpenManual = document.getElementById("btnOpenManual");
    var manualSearchEl = document.getElementById("manualCheckinSearch");
    var manualListEl = document.getElementById("manualCheckinList");
    var manualPrevBtn = document.getElementById("manualCheckinPrev");
    var manualNextBtn = document.getElementById("manualCheckinNext");
    var manualPageInfo = document.getElementById("manualCheckinPageInfo");
    var manualCountEl = document.getElementById("manualCheckinCount");
    var manualQuickForm = document.getElementById("manualQuickCheckinForm");
    var manualQuickAction = document.getElementById("manualQuickCheckinAction");
    var manualQuickMemberId = document.getElementById("manualQuickCheckinMemberId");
    var manualQuickTrainerId = document.getElementById("manualQuickCheckinTrainerId");

    var manualState = { page: 1, numPages: 1, search: "", loading: false };
    var manualSearchTimer = null;

    function escapeHtml(str) {
        return String(str == null ? "" : str)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function renderManualMembers(data) {
        if (!manualListEl) return;
        var rows = data.members || [];
        if (!rows.length) {
            manualListEl.innerHTML =
                '<div class="entrix-manual-empty">' +
                '<i class="bi bi-people"></i>' +
                (manualState.search
                    ? "No active members or trainers match your search."
                    : "No active members or trainers available for check-in.") +
                "</div>";
        } else {
            var html = "";
            rows.forEach(function (m) {
                var isTrainer = m.kind === "trainer";
                var action = m.is_inside
                    ? '<button type="button" class="btn btn-sm btn-success-subtle text-success border-0 entrix-manual-action" disabled>' +
                      '<i class="bi bi-check-circle-fill me-1"></i>Inside</button>'
                    : '<button type="button" class="btn btn-sm btn-brand rounded-pill px-3 entrix-manual-action btn-quick-checkin" ' +
                      'data-kind="' + (isTrainer ? "trainer" : "member") + '" ' +
                      'data-code="' + escapeHtml(m.code) + '">' +
                      '<i class="bi bi-box-arrow-in-right me-1"></i>Quick Check-In</button>';

                var roleBadge = isTrainer
                    ? '<span class="entrix-manual-role badge bg-warning-subtle text-warning-emphasis border border-warning-subtle">Trainer</span>'
                    : '<span class="entrix-manual-role badge bg-primary-subtle text-primary border border-primary-subtle">Member</span>';

                var detailLine = isTrainer
                    ? '<i class="bi bi-person-badge me-1"></i>' + escapeHtml(m.detail)
                    : '<i class="bi bi-card-checklist me-1"></i>' + escapeHtml(m.detail) +
                      (m.expiry_date ? ' &middot; <i class="bi bi-calendar-event me-1"></i>Expires ' + escapeHtml(m.expiry_date) : "");

                html +=
                    '<div class="entrix-manual-row">' +
                    '<div class="entrix-manual-info">' +
                    '<div class="entrix-manual-name text-truncate">' + escapeHtml(m.full_name) + " " + roleBadge + "</div>" +
                    '<div class="entrix-manual-meta text-truncate">' +
                    '<span class="me-2">' + escapeHtml(m.code) + "</span>" +
                    '<span class="me-2"><i class="bi bi-telephone me-1"></i>' + escapeHtml(m.mobile_number) + "</span>" +
                    "</div>" +
                    '<div class="entrix-manual-meta text-truncate">' + detailLine + "</div>" +
                    "</div>" +
                    '<div class="entrix-manual-action">' + action + "</div>" +
                    "</div>";
            });
            manualListEl.innerHTML = html;
        }

        manualState.page = data.page || 1;
        manualState.numPages = data.num_pages || 1;
        if (manualPageInfo) manualPageInfo.textContent = "Page " + manualState.page + " / " + manualState.numPages;
        if (manualPrevBtn) manualPrevBtn.disabled = !data.has_previous;
        if (manualNextBtn) manualNextBtn.disabled = !data.has_next;
        if (manualCountEl) {
            manualCountEl.textContent = (data.total || 0) + " eligible" + ((data.total === 1) ? " record" : " records");
        }
    }

    function loadManualMembers() {
        if (!manualListEl || manualState.loading) return;
        manualState.loading = true;
        manualListEl.innerHTML =
            '<div class="text-center text-muted py-5">' +
            '<div class="spinner-border text-primary" role="status"></div>' +
            '<div class="mt-2">Loading members...</div></div>';
        var url = "?action=manual_checkin_members&page=" + manualState.page +
            "&search=" + encodeURIComponent(manualState.search);
        fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                manualState.loading = false;
                renderManualMembers(data);
            })
            .catch(function () {
                manualState.loading = false;
                if (manualListEl) {
                    manualListEl.innerHTML =
                        '<div class="entrix-manual-empty"><i class="bi bi-exclamation-triangle"></i>' +
                        "Could not load members. Please try again.</div>";
                }
            });
    }

    if (btnOpenManual && manualModal) {
        btnOpenManual.addEventListener("click", function () {
            manualState.page = 1;
            manualState.search = "";
            if (manualSearchEl) manualSearchEl.value = "";
            manualModal.show();
            loadManualMembers();
        });
    }

    if (manualSearchEl) {
        manualSearchEl.addEventListener("input", function () {
            clearTimeout(manualSearchTimer);
            manualSearchTimer = setTimeout(function () {
                manualState.search = manualSearchEl.value.trim();
                manualState.page = 1;
                loadManualMembers();
            }, 300);
        });
    }

    if (manualPrevBtn) {
        manualPrevBtn.addEventListener("click", function () {
            if (manualState.page > 1) {
                manualState.page -= 1;
                loadManualMembers();
            }
        });
    }
    if (manualNextBtn) {
        manualNextBtn.addEventListener("click", function () {
            if (manualState.page < manualState.numPages) {
                manualState.page += 1;
                loadManualMembers();
            }
        });
    }

    if (manualListEl && manualQuickForm && manualQuickAction) {
        manualListEl.addEventListener("click", function (e) {
            var btn = e.target.closest(".btn-quick-checkin");
            if (!btn) return;
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            var kind = btn.getAttribute("data-kind");
            var code = btn.getAttribute("data-code");
            if (kind === "trainer") {
                manualQuickAction.value = "trainer_check_in";
                if (manualQuickTrainerId) manualQuickTrainerId.value = code;
                if (manualQuickMemberId) manualQuickMemberId.value = "";
            } else {
                manualQuickAction.value = "check_in";
                if (manualQuickMemberId) manualQuickMemberId.value = code;
                if (manualQuickTrainerId) manualQuickTrainerId.value = "";
            }
            manualQuickForm.submit();
        });
    }

    // --- Shared: fetch member details and populate/open the member modal ---
    // Reused by the attendance member rows, the expired-members list, and the
    // dashboard "View Profile" deep-link (?view_member=<id>).
    function openMemberModal(memberId) {
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
            setModalRole("member");
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
            if (document.getElementById("modalDob")) document.getElementById("modalDob").textContent = data.dob || "--";
            document.getElementById("modalMobile").textContent = data.mobile;
            if (document.getElementById("modalEmail")) document.getElementById("modalEmail").textContent = data.email || "--";
            if (document.getElementById("modalUsername")) document.getElementById("modalUsername").textContent = data.username || "--";
            if (document.getElementById("modalAddress")) document.getElementById("modalAddress").textContent = data.address || "--";
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
    }

    // --- View Member Details via AJAX ---
    document.querySelectorAll(".btn-view-member").forEach(function (btn) {
        btn.addEventListener("click", function () {
            openMemberModal(btn.getAttribute("data-member-id"));
        });
    });

    // --- Dashboard deep-link: open a member profile directly (?view_member=<id>) ---
    (function handleViewMemberDeepLink() {
        try {
            var params = new URLSearchParams(window.location.search);
            var deepLinkId = params.get("view_member");
            if (deepLinkId) {
                openMemberModal(deepLinkId);
            }
        } catch (e) {
            console.error("view_member deep-link failed:", e);
        }
    })();

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
                // Switch the shared modal into trainer mode: hides the
                // member-only Health/Membership cards (Plan Details, Plan
                // Amount, etc.) and reveals the trainer Employment card.
                setModalRole("trainer");

                document.getElementById("modalMemberName").textContent = data.name;
                document.getElementById("modalMemberId").textContent = data.id;
                document.getElementById("modalMemberPhoto").src = data.photo_url;

                var statusBadge = document.getElementById("modalStatusBadge");
                statusBadge.className = "badge bg-success ms-auto";
                statusBadge.textContent = data.status || "Trainer";

                // Basic Info (shared card)
                document.getElementById("modalGender").textContent = data.gender;
                document.getElementById("modalBlood").textContent = data.blood_group;
                if (document.getElementById("modalDob")) document.getElementById("modalDob").textContent = data.dob || "--";
                document.getElementById("modalMobile").textContent = data.mobile;
                if (document.getElementById("modalEmail")) document.getElementById("modalEmail").textContent = data.email || "--";
                if (document.getElementById("modalUsername")) document.getElementById("modalUsername").textContent = data.username || "--";
                if (document.getElementById("modalAddress")) document.getElementById("modalAddress").textContent = data.address || "--";
                document.getElementById("modalJoinDate").textContent = data.join_date;

                // Employment Info (trainer-only card)
                document.getElementById("modalTrainerDesignation").textContent = data.designation || "--";
                document.getElementById("modalTrainerStatus").textContent = data.status || "--";
                document.getElementById("modalTrainerTime").textContent = data.working_time || "--";
                document.getElementById("modalTrainerJoinedSince").textContent = data.joined_since || "--";

                // Attendance Summary pills (shared, relevant to trainers too)
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
    // Change 7 — "Access Denied" alerts must stay dismissed across refreshes.
    // Only these (data-alert-type="denied") persist, via localStorage keyed by
    // a stable per-alert key from the server. All other alerts keep their
    // original session-only dismiss behaviour (removed only for this view).
    var DENIED_DISMISS_STORE = "entrixDismissedDeniedAlerts";

    function getDismissedDeniedKeys() {
        try {
            return JSON.parse(window.localStorage.getItem(DENIED_DISMISS_STORE)) || [];
        } catch (e) {
            return [];
        }
    }

    function persistDismissedDeniedKey(key) {
        if (!key) return;
        try {
            var keys = getDismissedDeniedKeys();
            if (keys.indexOf(key) === -1) {
                keys.push(key);
                window.localStorage.setItem(DENIED_DISMISS_STORE, JSON.stringify(keys));
            }
        } catch (e) {
            /* localStorage unavailable — fall back to session-only removal */
        }
    }

    function collapseAlertsSectionIfEmpty() {
        var section = document.getElementById("securityAlertsSection");
        if (section && !section.querySelector(".entrix-alert-card, .entrix-alert-banner")) {
            section.remove();
        }
    }

    // On load, remove any Access Denied alerts the operator already dismissed.
    (function hidePreviouslyDismissedDeniedAlerts() {
        var dismissed = getDismissedDeniedKeys();
        if (!dismissed.length) return;
        document.querySelectorAll('.entrix-alert-card[data-alert-type="denied"]').forEach(function (card) {
            var key = card.getAttribute("data-dismiss-key");
            if (key && dismissed.indexOf(key) !== -1) {
                card.remove();
            }
        });
        collapseAlertsSectionIfEmpty();
    })();

    document.querySelectorAll(".btn-dismiss-alert").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var banner = btn.closest(".entrix-alert-card, .entrix-alert-banner");
            if (!banner) return;

            // Only Access Denied alerts are remembered across refreshes.
            if (banner.getAttribute("data-alert-type") === "denied") {
                persistDismissedDeniedKey(banner.getAttribute("data-dismiss-key"));
            }

            banner.style.opacity = "0";
            banner.style.transform = "translateY(-10px)";
            setTimeout(function () {
                banner.remove();
                collapseAlertsSectionIfEmpty();
            }, 300);
        });
    });

    // --- Alert avatar -> full-size image popup (image only) ---
    var alertImageModalEl = document.getElementById("alertImageModal");
    var alertImageModal = alertImageModalEl ? new bootstrap.Modal(alertImageModalEl) : null;
    var alertImageModalImg = document.getElementById("alertImageModalImg");

    function openAlertImage(photoUrl, name) {
        if (!alertImageModal || !alertImageModalImg || !photoUrl) {
            return;
        }
        alertImageModalImg.src = photoUrl;
        alertImageModalImg.alt = name || "";
        alertImageModal.show();
    }

    document.querySelectorAll(".btn-alert-photo").forEach(function (img) {
        img.addEventListener("click", function () {
            openAlertImage(img.getAttribute("data-photo-url"), img.getAttribute("data-name"));
        });
        img.addEventListener("keydown", function (e) {
            if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                openAlertImage(img.getAttribute("data-photo-url"), img.getAttribute("data-name"));
            }
        });
    });

    // --- View Member Details from Expired Modal ---
    document.querySelectorAll(".btn-view-expired-member").forEach(function (btn) {
        btn.addEventListener("click", function () {
            if (expiredModal) {
                expiredModal.hide();
            }
            openMemberModal(btn.getAttribute("data-member-id"));
        });
    });


});

