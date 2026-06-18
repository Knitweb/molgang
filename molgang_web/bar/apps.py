"""App config for the MOLGANG bar front-end."""

from __future__ import annotations

from django.apps import AppConfig


class BarConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "bar"
    verbose_name = "MOLGANG bar"
