"""
HTTP endpoints for the eSSL ADMS (iclock PUSH) protocol.

These views translate raw device HTTP traffic into calls on the protocol
handler in ``transactions.adms``. They are deliberately thin — parsing and
business rules live in ``adms`` / ``services`` — and are CSRF-exempt because
the client is a hardware device, not a browser session. Security is enforced
by device serial allow-list + optional shared key inside ``adms``.
"""

import logging

from django.http import HttpResponse, HttpResponseForbidden
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from . import adms

logger = logging.getLogger("entrix.adms")


def _authorize(request):
    serial = request.GET.get("SN") or request.GET.get("sn") or ""
    key = request.GET.get("pushver") or request.headers.get("X-Adms-Key", "")
    ip = request.META.get("REMOTE_ADDR")

    if not adms.is_device_authorized(serial, ip_address=ip):
        logger.warning("ADMS: rejected unauthorized/unapproved device serial=%r", serial)
        return HttpResponseForbidden("Unauthorized device")
    if not adms.verify_shared_key(key):
        logger.warning("ADMS: rejected bad shared key for serial=%r", serial)
        return HttpResponseForbidden("Invalid key")
    return None


@method_decorator(csrf_exempt, name="dispatch")
class IClockCDataView(View):
    """
    ``/iclock/cdata``

    * GET  — device handshake on boot. We reply with the registry/options
             block the firmware expects so it starts pushing data.
    * POST — real-time attendance push (ATTLOG) and other tables. We record
             attendance punches and always answer ``OK`` so the device marks
             the batch as delivered.
    """

    def get(self, request, *args, **kwargs):
       
        denied = _authorize(request)
        if denied:
            return denied
        serial = request.GET.get("SN", "")
        # Standard iclock registry handshake response.
        body = (
            "GET OPTION FROM: {sn}\r\n"
            "STAMP=9999\r\n"
            "OpStamp=9999\r\n"
            "ErrorDelay=30\r\n"
            "Delay=10\r\n"
            "TransTimes=00:00;14:05\r\n"
            "TransInterval=1\r\n"
            "TransFlag=1111000000\r\n"
            "Realtime=1\r\n"
            "Encrypt=0\r\n"
        ).format(sn=serial)
        return HttpResponse(body, content_type="text/plain")

    def post(self, request, *args, **kwargs):
        
        denied = _authorize(request)
        if denied:
            return denied

        table = request.GET.get("table", "ATTLOG")
        raw = request.body.decode("utf-8", errors="replace")

        if table.upper() == "ATTLOG":
            summary = adms.process_attlog_batch(raw)
            logger.info("ADMS ATTLOG batch from %s: %s",
                        request.GET.get("SN", "?"), summary)
            # The device counts records by the OK line; echo how many we took.
            return HttpResponse("OK: %d" % summary["received"], content_type="text/plain")

        # OPERLOG / USERINFO / other tables are acknowledged but not processed
        # here — attendance is the only table this integration consumes.
        return HttpResponse("OK", content_type="text/plain")


@method_decorator(csrf_exempt, name="dispatch")
class IClockGetRequestView(View):
    """
    ``/iclock/getrequest``

    The device polls this endpoint for server-issued commands (e.g. sync time,
    re-upload logs). This integration is receive-only, so we always reply with
    an empty ``OK`` — no commands are queued.
    """

    def get(self, request, *args, **kwargs):
        
        denied = _authorize(request)
        if denied:
            return denied
        return HttpResponse("OK", content_type="text/plain")

    def post(self, request, *args, **kwargs):
        return self.get(request, *args, **kwargs)


@method_decorator(csrf_exempt, name="dispatch")
class IClockPingView(View):
    """
    ``/iclock/ping`` — lightweight liveness check some firmware issues before
    pushing. Always ``OK`` for authorized devices.
    """

    def get(self, request, *args, **kwargs):
      
        denied = _authorize(request)
        if denied:
            return denied
        return HttpResponse("OK", content_type="text/plain")
