import hashlib
import secrets

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

MCP_TOKEN_PREFIX = "rmbl_"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    minute_cap = models.PositiveIntegerField(
        default=600,
        help_text="Recording allowance per calendar month, in minutes.",
    )
    billed_seconds = models.FloatField(
        default=0,
        help_text="Lifetime AssemblyAI audio total (audit); monthly allowance uses usage logs.",
    )
    mcp_token_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    mcp_token_prefix = models.CharField(max_length=12, blank=True, default="")
    mcp_token_created_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email

    @property
    def has_mcp_token(self):
        return bool(self.mcp_token_hash)

    def issue_mcp_token(self):
        raw = MCP_TOKEN_PREFIX + secrets.token_urlsafe(32)
        self.mcp_token_hash = hash_mcp_token(raw)
        self.mcp_token_prefix = raw[:12]
        self.mcp_token_created_at = timezone.now()
        self.save(update_fields=["mcp_token_hash", "mcp_token_prefix", "mcp_token_created_at"])
        return raw

    @classmethod
    def get_by_mcp_token(cls, raw):
        token = (raw or "").strip()
        if not token:
            return None
        return (
            cls.objects.filter(
                mcp_token_hash=hash_mcp_token(token),
                is_active=True,
            )
            .exclude(mcp_token_hash="")
            .first()
        )


def hash_mcp_token(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
