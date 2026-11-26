import re

from django import forms
from django.utils import timezone
from django.utils.text import slugify

from .models import BlogPost, SupportRequest

TEXTAREA_ATTRS = {
    "class": "field support-textarea",
    "rows": 6,
    "placeholder": "What can we help with?",
}

BLOG_FIELD_ATTRS = {
    "class": "field blog-input",
}

# Root /<slug>/ posts must not collide with app or marketing paths.
BLOG_RESERVED_SLUGS = frozenset(
    {
        "admin",
        "albums",
        "api",
        "blog",
        "celebrants",
        "crm",
        "healthz",
        "kpi",
        "library",
        "llms",
        "login",
        "logout",
        "mcp",
        "notes",
        "oauth",
        "privacy",
        "robots",
        "roll",
        "settings",
        "signup",
        "sitemap",
        "static",
        "support",
        "t",
        "terms",
    }
)


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


class BlogPostForm(forms.ModelForm):
    class Meta:
        model = BlogPost
        fields = (
            "title",
            "heading",
            "slug",
            "section",
            "excerpt",
            "meta_description",
            "seo_notes",
            "body",
            "is_published",
        )
        labels = {
            "is_published": "Published",
            "meta_description": "Meta description",
            "seo_notes": "SEO notes (private)",
            "heading": "H1",
            "section": "Section",
            "excerpt": "Index excerpt",
        }
        widgets = {
            "title": forms.TextInput(
                attrs={**BLOG_FIELD_ATTRS, "placeholder": "Title for tab and social share"}
            ),
            "heading": forms.TextInput(
                attrs={
                    **BLOG_FIELD_ATTRS,
                    "placeholder": "H1 on the page (defaults to title)",
                }
            ),
            "slug": forms.TextInput(
                attrs={
                    **BLOG_FIELD_ATTRS,
                    "placeholder": "your-post-title (auto from title if blank)",
                    "spellcheck": "false",
                }
            ),
            "section": forms.Select(attrs={**BLOG_FIELD_ATTRS}),
            "excerpt": forms.Textarea(
                attrs={
                    **BLOG_FIELD_ATTRS,
                    "placeholder": "Short summary for the index listing",
                    "rows": 2,
                }
            ),
            "meta_description": forms.Textarea(
                attrs={
                    **BLOG_FIELD_ATTRS,
                    "placeholder": (
                        "Meta / OG / Twitter description — about 150 characters, max 155"
                    ),
                    "rows": 3,
                    "maxlength": "155",
                }
            ),
            "seo_notes": forms.Textarea(
                attrs={
                    **BLOG_FIELD_ATTRS,
                    "placeholder": (
                        "Private: target phrases, autocomplete checks, research notes"
                    ),
                    "rows": 4,
                }
            ),
            "body": forms.Textarea(
                attrs={
                    **BLOG_FIELD_ATTRS,
                    "placeholder": (
                        "Write the post. Separate paragraphs with a blank line.\n"
                        "Links: [Ramble](https://yourramble.com) or paste a URL."
                    ),
                    "rows": 18,
                }
            ),
            "is_published": forms.CheckboxInput(attrs={"class": "blog-checkbox"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["heading"].required = False
        self.fields["excerpt"].required = False
        self.fields["meta_description"].required = False
        self.fields["seo_notes"].required = False
        self.fields["is_published"].required = False
        self.fields["section"].required = False

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("Add a title.")
        return title

    def clean_heading(self):
        return (self.cleaned_data.get("heading") or "").strip()

    def clean_excerpt(self):
        return (self.cleaned_data.get("excerpt") or "").strip()

    def clean_meta_description(self):
        return (self.cleaned_data.get("meta_description") or "").strip()

    def clean_seo_notes(self):
        return (self.cleaned_data.get("seo_notes") or "").strip()

    def clean_body(self):
        body = (self.cleaned_data.get("body") or "").strip()
        if not body:
            raise forms.ValidationError("Add some body text.")
        return body

    def clean_section(self):
        return self.cleaned_data.get("section") or BlogPost.Section.BLOG

    def clean_slug(self):
        slug = (self.cleaned_data.get("slug") or "").strip().lower()
        if not slug:
            title = self.data.get("title", "")
            slug = slugify(title)[:220]
        slug = re.sub(r"[^a-z0-9_-]+", "-", slug).strip("-")[:220]
        if not slug:
            raise forms.ValidationError("Add a slug, or a title to derive one.")
        if slug in BLOG_RESERVED_SLUGS:
            raise forms.ValidationError("That URL is reserved. Choose another slug.")
        qs = BlogPost.objects.filter(slug=slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("That slug is already in use.")
        return slug

    def save(self, commit=True):
        post = super().save(commit=False)
        if post.is_published and post.published_at is None:
            post.published_at = timezone.now()
        if commit:
            post.save()
        return post
