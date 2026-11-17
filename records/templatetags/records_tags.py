from django import template

register = template.Library()

STATUS_CLASSES = {
    "REPORTED": "secondary",
    "UNDER_INVESTIGATION": "primary",
    "FORWARDED": "warning",
    "CLOSED": "dark",
    "DRAFT": "warning",
    "FINALIZED": "success",
}


@register.filter
def status_class(value):
    return STATUS_CLASSES.get(str(value), "secondary")


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    """Rebuild the current query string with some parameters replaced (for pagination)."""
    params = context["request"].GET.copy()
    for k, v in kwargs.items():
        params[k] = v
    return params.urlencode()
