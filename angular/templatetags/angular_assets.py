import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def static_versioned(path: str) -> str:
    asset_url = static(path)
    absolute_path = finders.find(path)
    if not absolute_path:
        return asset_url

    try:
        version = int(os.path.getmtime(absolute_path))
    except OSError:
        return asset_url

    separator = '&' if '?' in asset_url else '?'
    return f'{asset_url}{separator}v={version}'
