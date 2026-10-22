from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def exercise_thumb(name, cover=''):
    """Small square exercise picture; a letter tile when the exercise has no image (most library entries are text only)."""
    if cover:
        return format_html('<img class="ex-thumb" src="{}" alt="{}" title="{}" loading="lazy">', cover, name, name)
    return format_html('<span class="ex-thumb ex-thumb-blank" title="{}">{}</span>', name, (name or '?').strip()[:1].upper())
