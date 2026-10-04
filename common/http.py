# common/http.py

import ipaddress

from django.utils.http import url_has_allowed_host_and_scheme


def safe_next_url(request, next_url, fallback):
    """``next_url`` if it points back into this site, otherwise ``fallback``."""
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback


def get_client_ip(request):
    """
    The visitor's IP address, or None.

    Each Nginx hop appends to X-Forwarded-For, and anything to the left of
    our own proxies is whatever the client sent. Reading from the right and
    skipping private addresses (our proxies) gives the first address one of
    our proxies actually saw, so a forged header can't choose the result.
    """
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    candidates = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    candidates.reverse()
    candidates.append(request.META.get("REMOTE_ADDR", ""))

    fallback = None
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.is_global:
            return str(address)
        fallback = fallback or str(address)

    return fallback
