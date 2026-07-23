/**
 * TRANSACTIONS APP — Global Alert Notifications
 * Polls the backend for active security/limit alerts every 10 seconds.
 * Plays a notification sound universally across all pages.
 */
(function() {
    "use strict";
    
    var DENIED_DISMISS_STORE = "entrixDismissedDeniedAlerts";
    var PREV_ALERTS_KEY = "entrixGlobalPrevAlertKeys";
    var POLL_INTERVAL_MS = 10000; // 10 seconds
    
    var alertBeepOscillator = null;
    var alertBeepContext = null;
    var isSilenced = false;
    
    function getDismissedDeniedKeys() {
        try {
            return JSON.parse(window.localStorage.getItem(DENIED_DISMISS_STORE)) || [];
        } catch (e) {
            return [];
        }
    }
    
    function playAlertBeep() {
        if (isSilenced) return;
        if (!window.AudioContext && !window.webkitAudioContext) return;
        
        if (alertBeepContext) {
            alertBeepContext.close();
        }
        
        try {
            alertBeepContext = new (window.AudioContext || window.webkitAudioContext)();
            alertBeepOscillator = alertBeepContext.createOscillator();
            alertBeepOscillator.type = 'sine';
            alertBeepOscillator.frequency.setValueAtTime(800, alertBeepContext.currentTime);
            
            var gainNode = alertBeepContext.createGain();
            gainNode.gain.setValueAtTime(0, alertBeepContext.currentTime);
            
            // Loop a pulsing beep for up to 30 seconds
            for (var i = 0; i < 30; i++) {
                gainNode.gain.setValueAtTime(1, alertBeepContext.currentTime + i);
                gainNode.gain.setValueAtTime(0, alertBeepContext.currentTime + i + 0.5);
            }
            
            alertBeepOscillator.connect(gainNode);
            gainNode.connect(alertBeepContext.destination);
            alertBeepOscillator.start();
            alertBeepOscillator.stop(alertBeepContext.currentTime + 30);
        } catch (e) {
            console.error("Audio playback failed:", e);
        }
    }
    
    function stopAlertBeep() {
        if (alertBeepOscillator) {
            try { alertBeepOscillator.stop(); } catch (e) {}
            alertBeepOscillator = null;
        }
        if (alertBeepContext) {
            try { alertBeepContext.close(); } catch (e) {}
            alertBeepContext = null;
        }
    }
    
    // Listen for silence button click if the button exists on the page
    document.addEventListener("click", function(e) {
        var btn = e.target.closest(".btn-silence-alert");
        if (btn) {
            isSilenced = true;
            stopAlertBeep();
            
            // Update all silence buttons on the page
            document.querySelectorAll(".btn-silence-alert").forEach(function(b) {
                b.innerHTML = '<i class="bi bi-volume-mute me-1"></i>Silenced';
                b.disabled = true;
            });
        }
    });
    
    function pollAlerts() {
        fetch("/attendance-management/?action=poll_alerts", {
            headers: {
                "X-Requested-With": "XMLHttpRequest"
            }
        })
        .then(function(res) {
            if (!res.ok) throw new Error("Poll failed");
            return res.json();
        })
        .then(function(data) {
            if (!data.alert_keys) return;
            
            var currentAlertKeys = data.alert_keys;
            var dismissed = getDismissedDeniedKeys();
            
            // Filter out dismissed denied alerts
            currentAlertKeys = currentAlertKeys.filter(function(key) {
                if (key.startsWith("denied-") && dismissed.indexOf(key) !== -1) {
                    return false;
                }
                return true;
            });
            
            var prevAlertKeys = [];
            try {
                prevAlertKeys = JSON.parse(sessionStorage.getItem(PREV_ALERTS_KEY)) || [];
            } catch (e) {}
            
            var hasNewAlert = false;
            for (var i = 0; i < currentAlertKeys.length; i++) {
                // Only play sound for Time Limit Exceeded and Maximum Occupancy Exceeded
                if (!currentAlertKeys[i].startsWith("time_limit-") && !currentAlertKeys[i].startsWith("occupancy-")) continue;

                if (prevAlertKeys.indexOf(currentAlertKeys[i]) === -1) {
                    hasNewAlert = true;
                    break;
                }
            }
            
            if (hasNewAlert) {
                playAlertBeep();
            }
            
            try {
                sessionStorage.setItem(PREV_ALERTS_KEY, JSON.stringify(currentAlertKeys));
            } catch (e) {}
        })
        .catch(function(err) {
            // Silently ignore errors during polling to not flood console
        });
    }

    // Start polling if not disabled
    setInterval(pollAlerts, POLL_INTERVAL_MS);
    
    // Initial check on load after 2 seconds
    setTimeout(pollAlerts, 2000);
})();
