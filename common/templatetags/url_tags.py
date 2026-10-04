# common/templatetags/url_tags.py

from django import template
from django.utils.http import url_has_allowed_host_and_scheme

register = template.Library()


@register.filter
def local_url(value):
    """
    ``value`` if it is a path on this site, otherwise "".

    Used for "Back" links built from ``?next=`` so a crafted link can't send
    staff to another site or run a ``javascript:`` URL.
    """
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts=None):
        return value
    return ""
