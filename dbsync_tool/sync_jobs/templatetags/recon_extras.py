"""Day-6 reconciliation template helpers used by ``execution_detail.html``.

Two helpers:
  - ``recon_for``: simple tag that resolves the per-table decision/confidence
    block from the ``recon_by_table`` mapping injected by the view.
  - ``decision_chip_class`` / ``decision_chip_label`` / ``confidence_pct``:
    cosmetic filters for the chip rendering.
"""

from __future__ import annotations

from django import template

register = template.Library()


_UNKNOWN = {"decision": "unknown", "confidence": None}


@register.simple_tag
def recon_for(mapping, schema_name, table_name):
    """Return ``{decision, confidence}`` for ``(schema, table)`` in mapping.

    Mapping may be tuple-keyed or string-keyed (``"schema|table"``).  Missing
    entries return an ``unknown`` block instead of None so the template can
    render a fallback chip without conditional NoneType checks.
    """
    if not mapping:
        return dict(_UNKNOWN)
    if isinstance(mapping, dict):
        tuple_key = (schema_name, table_name)
        if tuple_key in mapping:
            return mapping[tuple_key]
        str_key = f"{schema_name}|{table_name}"
        if str_key in mapping:
            return mapping[str_key]
    return dict(_UNKNOWN)


@register.filter
def decision_chip_class(decision):
    """CSS class fragment for the per-table Quality chip."""
    value = (decision or "unknown").lower()
    if value == "ok":
        return "bg-emerald-50 text-emerald-600 border-emerald-100"
    if value == "warning":
        return "bg-amber-50 text-amber-700 border-amber-100"
    if value in ("repair_full", "repair_incremental"):
        return "bg-red-50 text-red-600 border-red-100"
    return "bg-slate-50 text-slate-500 border-slate-100"


@register.filter
def decision_chip_label(decision):
    """Display label for the per-table Quality chip."""
    value = (decision or "unknown").lower()
    if value == "ok":
        return "OK"
    if value == "warning":
        return "WARNING"
    if value == "repair_full":
        return "REPAIR FULL"
    if value == "repair_incremental":
        return "REPAIR INCREMENTAL"
    return "UNKNOWN"


@register.filter
def confidence_pct(value):
    """Render confidence as ``0.70`` style two-decimal string or empty."""
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""
