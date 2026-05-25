# Notification Features Documentation

This document describes the two new production-quality features added to the DB Sync Tool:

1. **Server Shutdown / Crash Email Alerts**
2. **Notification Recipients Management UI**

---

## Feature 1: Server Shutdown / Crash Email Alert

### Overview
Automatically sends email alerts when the Django development server stops, whether gracefully (Ctrl+C) or due to a crash.

### Usage

Instead of running the standard Django development server with:
```bash
python manage.py runserver 8004
```

Use the monitored version:
```bash
python manage.py runserver_monitored --port 8004
```

Or with custom host:
```bash
python manage.py runserver_monitored --host 0.0.0.0 --port 8004
```

### What Gets Monitored

The command monitors:
- **SIGINT** (Ctrl+C on Windows/Linux/macOS)
- **SIGTERM** (kill signal)
- **SIGBREAK** (Ctrl+Break on Windows)
- **Process crashes** (unhandled exceptions)
- **Normal exit** (graceful shutdown)

### Email Recipients

Alerts are sent to:
1. All **active** recipients from the database (Feature 2)
2. Fallback to `ADMIN_EMAILS` from `.env` if no DB recipients exist

### Email Content

The alert email includes:
- Project name ("DB Sync Tool")
- Server host and port
- Timestamp of shutdown
- Reason for shutdown (e.g., "keyboard_interrupt", "signal_SIGTERM", "process_exit_code_1")
- Status classification (Graceful vs Unexpected)

### Error Handling

- If email sending fails, the error is logged to `logs/email_errors.log`
- Email failures **never** block server shutdown
- All email operations are synchronous (no async dependencies)

### Cross-Platform Support

Works on:
- ✅ Windows (Ctrl+C, Ctrl+Break)
- ✅ Linux (SIGINT, SIGTERM)
- ✅ macOS (SIGINT, SIGTERM)

---

## Feature 2: Notification Recipients UI

### Overview
Web-based interface for managing email recipients who receive system alerts (like server shutdown notifications).

### Access

Navigate to: **http://localhost:8004/notifications/**

Or click **"Notifications"** in the sidebar (visible to Admins and Super Admins only).

### Features

#### 1. View All Recipients
- See all configured email recipients
- View their status (Active/Inactive)
- See when they were added
- Optional name field for identification

#### 2. Add New Recipient
- Click "Add Recipient" button
- Enter email address (required, validated)
- Optional: Enter a name for reference
- Email uniqueness is enforced
- Invalid emails are rejected

#### 3. Toggle Active/Inactive
- Click the toggle switch next to any recipient
- Inactive recipients won't receive notifications
- Useful for temporarily disabling alerts without deletion

#### 4. Delete Recipients
- Click the delete icon (trash can)
- Confirmation modal prevents accidental deletion
- Deletion is permanent

### REST API Endpoints

Backend APIs (all require authentication):

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/notification-recipients/` | List all recipients |
| POST | `/api/notification-recipients/create/` | Add new recipient |
| PATCH | `/api/notification-recipients/<id>/toggle/` | Toggle active status |
| DELETE | `/api/notification-recipients/<id>/delete/` | Delete recipient |

### Database Model

**Table:** `notification_recipients`

| Field | Type | Description |
|-------|------|-------------|
| `id` | BigInteger | Primary key |
| `email` | EmailField | Unique email address |
| `name` | CharField | Optional display name |
| `is_active` | BooleanField | Active status (default: True) |
| `created_at` | DateTimeField | Creation timestamp |
| `updated_at` | DateTimeField | Last update timestamp |

### UI Design

- Follows existing Azure design language
- Uses Material Symbols icons
- Responsive toast notifications for success/error
- Confirmation modals for destructive actions
- Matches sidebar and dashboard styling

---

## Email Configuration

Ensure your `.env` file has these settings:

```ini
# Email Backend Configuration
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=your-email@gmail.com

# Fallback admin emails (comma-separated)
ADMIN_EMAILS=admin@example.com,ops@example.com
```

### Gmail App Passwords

If using Gmail:
1. Enable 2-Factor Authentication
2. Generate an App Password: https://myaccount.google.com/apppasswords
3. Use the 16-character app password (not your regular password)

---

## Files Created/Modified

### New Files
1. `core/models.py` - Added `NotificationRecipient` model
2. `core/management/commands/runserver_monitored.py` - Monitored runserver command
3. `templates/notifications.html` - Frontend UI for managing recipients
4. `core/migrations/0001_add_notification_recipient_model.py` - Database migration
5. `NOTIFICATION_FEATURES.md` - This documentation file

### Modified Files
1. `core/views.py` - Added API endpoints and notifications page view
2. `core/urls.py` - Added routes for notifications and API
3. `templates/base.html` - Added "Notifications" link to sidebar

---

## Security Considerations

✅ **CSRF Protection:** All POST/PATCH/DELETE requests require CSRF tokens  
✅ **Authentication:** All endpoints require `@login_required`  
✅ **Email Validation:** Email format validated on backend  
✅ **Unique Constraint:** Prevents duplicate email addresses  
✅ **Error Logging:** Failed emails logged securely to `logs/email_errors.log`  
✅ **No Sensitive Data:** Emails contain only metadata (no passwords/secrets)  

---

## Testing

### Test Server Monitoring

1. Start monitored server:
   ```bash
   python manage.py runserver_monitored --port 8004
   ```

2. Stop it with Ctrl+C

3. Check your email inbox for the shutdown alert

4. If email fails, check `logs/email_errors.log`

### Test UI

1. Navigate to http://localhost:8004/notifications/
2. Add a test email address
3. Toggle it active/inactive
4. Delete it
5. Verify toast notifications appear

### Test API Directly

```bash
# List recipients (requires authentication cookie)
curl -X GET http://localhost:8004/api/notification-recipients/ \
  -H "Cookie: sessionid=YOUR_SESSION_ID"

# Add recipient
curl -X POST http://localhost:8004/api/notification-recipients/create/ \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: YOUR_CSRF_TOKEN" \
  -H "Cookie: sessionid=YOUR_SESSION_ID" \
  -d '{"email":"test@example.com","name":"Test User"}'
```

---

## Troubleshooting

### Email Not Sending

1. Check `.env` email configuration
2. Verify SMTP credentials are correct
3. Check `logs/email_errors.log` for details
4. Test with Django's test_email command:
   ```bash
   python manage.py test_email
   ```

### Recipients Not Loading

1. Check browser console for JavaScript errors
2. Verify database migration ran: `python manage.py showmigrations core`
3. Check API endpoint directly: http://localhost:8004/api/notification-recipients/

### Sidebar Link Not Showing

The "Notifications" link only appears for:
- Super Admins
- Admins

Regular users (Operators, Viewers) won't see it.

---

## Production Deployment Notes

### 1. Switch to Production Email Backend

For production, consider using:
- AWS SES
- SendGrid
- Mailgun
- Postmark

Update `.env`:
```ini
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
# ... etc
```

### 2. Rate Limiting

The monitored runserver is for **development only**. In production:
- Use Gunicorn/uWSGI with systemd/supervisor
- Monitor process crashes with systemd or external monitoring tools
- Consider implementing rate limiting on email alerts to prevent spam

### 3. Log Rotation

Ensure `logs/email_errors.log` is rotated:
```bash
# Example logrotate config
/path/to/dbsync_tool/logs/email_errors.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
}
```

### 4. Database Backups

The `notification_recipients` table should be included in regular backups.

---

## Future Enhancements

Potential improvements:
- [ ] Bulk import recipients from CSV
- [ ] Email templates customization
- [ ] Notification categories (shutdown only, errors only, all)
- [ ] Slack/Teams webhook integration
- [ ] SMS alerts via Twilio
- [ ] Email delivery status tracking
- [ ] Test email button (send test alert manually)

---

## Support

For issues or questions:
1. Check this documentation first
2. Review `logs/email_errors.log` for email failures
3. Check Django logs: `logs/dbsync.log`
4. Verify email settings with `python manage.py test_email`

---

**Last Updated:** 2024
**Author:** DB Sync Tool Development Team
