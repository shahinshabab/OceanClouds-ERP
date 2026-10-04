# common/numbering.py


def next_sequential_code(model, field, prefix, pad):
    """
    Return the next code such as INV004 for ``model.<field>``.

    Codes are compared as numbers, not text, so INV1000 follows INV999
    (text ordering would keep picking INV999 as the latest one).
    """
    highest = 0
    values = model.objects.filter(**{f"{field}__startswith": prefix}).values_list(field, flat=True)
    for value in values.iterator():
        suffix = value[len(prefix):]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{prefix}{highest + 1:0{pad}d}"
