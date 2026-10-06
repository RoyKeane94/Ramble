from django import forms

from .models import SupportRequest

TEXTAREA_ATTRS = {
    "class": "field support-textarea",
    "rows": 6,
    "placeholder": "What can we help with?",
}


class SupportRequestForm(forms.ModelForm):
    email = forms.EmailField(
        widget=forms.EmailInput(
            attrs={"class": "field", "placeholder": "Email", "autocomplete": "email"},
        ),
    )
    topic = forms.ChoiceField(
        choices=SupportRequest.Topic.choices,
        widget=forms.Select(attrs={"class": "field"}),
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs=TEXTAREA_ATTRS),
    )

    class Meta:
        model = SupportRequest
        fields = ("email", "topic", "message")
