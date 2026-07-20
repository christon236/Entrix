"""
eSSL ADMS (Automatic Data Master Server) integration layer
==========================================================

Production-ready handler for eSSL / ZKTeco biometric devices that use the
**iclock PUSH protocol** (a.k.a. ADMS). The device is configured with this
server's address as its "ADMS Server", and then autonomously:

  1. Handshakes on boot                     ->  GET  /iclock/cdata
  2. Pushes attendance punches in real time ->  POST /iclock/cdata (ATTLOG)
  3. Polls for server commands              ->  GET  /iclock/getrequest

Design goals
------------
* **Modular** — all protocol parsing lives here; the actual attendance rules
  live in ``transactions.services`` and are shared with the manual flow.
* **Secure** — every request is authenticated by the device serial number
  against an allow-list (``ESSL_ADMS_DEVICE_SERIALS``) and an optional shared
  key. Unknown devices are rejected with 401.
* **Robust** — malformed lines are skipped and logged, never crash the feed;
  the endpoint always replies with the exact ``OK`` body the device expects so
  it marks records as delivered and doesn't resend forever.

This module intentionally has **no Django view/URL knowledge** — it exposes
pure functions that ``views_adms`` wires to HTTP. That keeps it unit-testable
and easy to maintain.
"""

import logging

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .services import record_biometric_punch

logger = logging.getLogger("entrix.adms")


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _allowed_serials():
    """Serial numbers permitted to push data. Empty list disables the check
    (useful only in a trusted/dev network — configure this in production)."""
    return [s.strip() for s in getattr(settings, "ESSL_ADMS_DEVICE_SERIALS", []) if s.strip()]


from .models import AdmsDevice  # adjust import path to wherever you put it

def is_device_authorized(serial, ip_address=None):
    """
    Every serial that reaches us is captured into AdmsDevice automatically.
    Authorization then depends on is_approved — new devices show up in Django
    admin as 'pending' instead of silently passing or silently vanishing.
    """
    serial = (serial or "").strip()
    if not serial:
        return False

    device, created = AdmsDevice.objects.get_or_create(
        serial_number=serial,
        defaults={"ip_address": ip_address},
    )
    if created:
        logger.warning("ADMS: new device auto-captured, pending approval: %s", serial)
    else:
        device.ip_address = ip_address or device.ip_address
        device.save(update_fields=["ip_address", "last_seen"])

    # Optional legacy allow-list still honored, so you don't have to migrate
    # existing settings.ESSL_ADMS_DEVICE_SERIALS right away.
    if serial in _allowed_serials():
        return True

    return device.is_approved


def verify_shared_key(provided_key):
    """Optional shared-secret check (device 'ADMS Auth' / pushver key)."""
    expected = getattr(settings, "ESSL_ADMS_SHARED_KEY", "") or ""
    if not expected:
        return True
    return (provided_key or "") == expected


# ---------------------------------------------------------------------------
# Punch-state mapping
# ---------------------------------------------------------------------------
#
# eSSL ATTLOG "status" / verify-state codes vary by device. The most common
# convention places the *punch state* in the 3rd field:
#   0 = Check-In, 1 = Check-Out, 2/3 = Break, 4 = OT-In, 5 = OT-Out
# When the device is left on "auto" it emits 0/255, in which case we let the
# service layer decide direction automatically by toggling current state.

_CHECK_IN_STATES = {"0", "4"}
_CHECK_OUT_STATES = {"1", "5"}


def _direction_from_state(state):
    state = (state or "").strip()
    if state in _CHECK_IN_STATES:
        return "check_in"
    if state in _CHECK_OUT_STATES:
        return "check_out"
    return None  # auto-toggle


# ---------------------------------------------------------------------------
# ATTLOG parsing
# ---------------------------------------------------------------------------

def parse_attlog(raw_body):
    """
    Parse an ADMS ATTLOG payload into a list of normalised punch dicts.

    Each attendance line is tab-separated:
        PIN <TAB> DATETIME <TAB> STATUS <TAB> VERIFY <TAB> WORKCODE ...
    e.g. ``123456\t2026-07-17 09:14:03\t0\t1\t0``

    Returns a list of dicts: ``{"pin", "timestamp", "direction"}``. Malformed
    lines are skipped (and logged) so a single bad record never breaks the
    whole batch.
    """
    punches = []
    if not raw_body:
        return punches

    for line in raw_body.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            logger.warning("ADMS: skipping malformed ATTLOG line: %r", line)
            continue

        pin = parts[0].strip()
        ts_raw = parts[1].strip()
        state = parts[2].strip() if len(parts) > 2 else ""

        dt = parse_datetime(ts_raw)
        if dt is None:
            # Some firmware uses "YYYY-MM-DD HH:MM:SS" without timezone; the
            # parser above handles that, but guard against odd separators.
            logger.warning("ADMS: unparseable timestamp %r in line %r", ts_raw, line)
            continue

        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        dt = timezone.localtime(dt)

        punches.append({
            "pin": pin,
            "timestamp": dt,
            "direction": _direction_from_state(state),
        })
    return punches


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process_attlog_batch(raw_body):
    """
    Parse and record an entire ATTLOG batch pushed by a device.

    Returns a summary dict with counts, suitable for logging. Delegates all
    attendance rules (access control, check-in/out toggle, trainer vs member)
    to ``record_biometric_punch`` so behaviour matches the rest of the app.
    """
    punches = parse_attlog(raw_body)
    summary = {"received": len(punches), "check_in": 0, "check_out": 0,
               "denied": 0, "noop": 0, "errors": 0}

    for punch in punches:
        try:
            result = record_biometric_punch(
                punch["pin"],
                punch_time=punch["timestamp"].time(),
                punch_date=punch["timestamp"].date(),
                force_direction=punch["direction"],
            )
            if result.event in summary:
                summary[result.event] += 1
            logger.info("ADMS punch pin=%s -> %s (%s)",
                        punch["pin"], result.event, result.message)
        except Exception:  # pragma: no cover - defensive, never break the feed
            summary["errors"] += 1
            logger.exception("ADMS: failed to record punch for pin=%s", punch.get("pin"))

    return summary
