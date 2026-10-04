from django import forms


class BootstrapModelForm(forms.ModelForm):
    """
    Reusable Bootstrap ModelForm.
    Use this in CRM, Sales, Projects, Todos, etc.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            widget = field.widget
            existing = widget.attrs.get("class", "")

            if isinstance(widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(widget, forms.CheckboxSelectMultiple):
                # A group of checkboxes styles its own inputs.
                css_class = ""
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css_class = "form-select"
            else:
                css_class = "form-control"

            widget.attrs["class"] = f"{existing} {css_class}".strip()