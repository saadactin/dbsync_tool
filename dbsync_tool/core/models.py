from django.db import models
from django.core.validators import EmailValidator


class NotificationRecipient(models.Model):
    """
    Email recipients for system notifications (e.g., server shutdown alerts).
    Admins can manage this list via the Notifications UI.
    """
    email = models.EmailField(
        max_length=255,
        unique=True,
        validators=[EmailValidator()],
        help_text="Email address to receive notifications"
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional name for this recipient"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this recipient should receive notifications"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notification_recipients'
        ordering = ['-created_at']
        verbose_name = 'Notification Recipient'
        verbose_name_plural = 'Notification Recipients'

    def __str__(self):
        return f"{self.name} <{self.email}>" if self.name else self.email

