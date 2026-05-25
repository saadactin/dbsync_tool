# Server Shutdown Monitoring - Complete Guide

## ⚠️ CRITICAL: How to Start the Server

### ❌ WRONG (No email alerts):
```bash
python manage.py runserver 8004
```
This is the **plain Django runserver** - it will NOT send email alerts!

### ✅ CORRECT (With email alerts):
```bash
cd dbsync_tool
python manage.py runserver_monitored
```

Or use the batch script (double-click or run from terminal):
```bash
start_server.bat
```

---

## How It Works

### When You Press Ctrl+C:

1. **KeyboardInterrupt is caught immediately**
2. **Subprocess is terminated gracefully**
3. **Email is sent BEFORE shutdown** (synchronous)
4. **Process exits cleanly**

### What You'll See in Terminal:

```
======================================================================
  Starting MONITORED Django server on 127.0.0.1:8004
  Email alerts will be sent on shutdown/crash
  Press Ctrl+C to stop (email will be sent BEFORE shutdown)
======================================================================

Starting development server at http://127.0.0.1:8004/
Quit the server with CTRL-BREAK.

^C  <-- You pressed Ctrl+C

======================================================================
  Ctrl+C detected! Shutting down...
======================================================================

======================================================================
  Sending shutdown alert email...
======================================================================
  [OK] Email sent to 1 recipient(s):
       - saad.sayyed@actin.co.in
======================================================================
```

---

## Email Configuration

### Recipients

Emails are sent to:
1. **Database recipients** - Active users in `NotificationRecipient` table
2. **Fallback** - `ADMIN_EMAILS` from `.env` file

### Manage Recipients

Add/remove recipients at: **http://localhost:8004/notifications/**

### Email Content

```
Subject: [DB Sync Tool] Server Shutdown - manual_shutdown_ctrl_c

Body:
Server Shutdown Notification
============================================================

Project: DB Sync Tool
Server: 127.0.0.1:8004
Timestamp: 2024-05-22 14:30:15
Reason: manual_shutdown_ctrl_c

============================================================
This is an automated alert from the DB Sync Tool monitoring system.

To restart the server, run:
  python manage.py runserver_monitored
```

---

## Troubleshooting

### Problem: No email received after Ctrl+C

**Diagnosis:**

1. **Check if you used the correct command:**
   ```bash
   # Wrong - no monitoring:
   python manage.py runserver 8004
   
   # Correct - with monitoring:
   python manage.py runserver_monitored
   ```

2. **Check terminal output:**
   - Look for: `Starting MONITORED Django server`
   - After Ctrl+C, look for: `Email sent to X recipient(s)`
   
3. **Verify recipients configured:**
   ```bash
   python manage.py shell -c "from django.conf import settings; print(settings.ADMIN_EMAILS)"
   ```
   Should output: `['your-email@example.com']`

4. **Test SMTP independently:**
   ```bash
   python manage.py test_email
   ```
   Or:
   ```bash
   python manage.py shell -c "
   from django.core.mail import send_mail
   from django.conf import settings
   send_mail('Test', 'Test message', settings.DEFAULT_FROM_EMAIL, settings.ADMIN_EMAILS)
   print('Email sent!')
   "
   ```

5. **Check error logs:**
   ```bash
   cat logs/email_errors.log
   ```

---

## Configuration Requirements

### .env File Must Have:

```ini
# Email Backend
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False

# Credentials (Gmail requires App Password)
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=your-email@gmail.com

# Fallback Recipients
ADMIN_EMAILS=admin1@example.com,admin2@example.com
```

### Gmail App Password Setup:

1. Go to: https://myaccount.google.com/apppasswords
2. Enable 2-Factor Authentication first
3. Generate App Password for "Mail"
4. Use the 16-character password (no spaces) in `EMAIL_HOST_PASSWORD`

---

## Technical Details

### Why Not Use Signal Handlers?

Signal handlers (`signal.signal(signal.SIGINT, ...)`) are **unreliable on Windows** for catching Ctrl+C in subprocess patterns. The `KeyboardInterrupt` exception is more reliable.

### Implementation Pattern:

```python
def handle(self, *args, **options):
    process = None
    try:
        process = subprocess.Popen([...runserver command...])
        process.wait()  # Ctrl+C raises KeyboardInterrupt HERE
        
    except KeyboardInterrupt:
        # THIS ALWAYS FIRES on Ctrl+C
        process.terminate()
        send_email()  # Send BEFORE exit
        sys.exit(0)
```

### Why Synchronous Email?

Email is sent **synchronously** (blocking) to ensure it completes before the process exits. Async/background email sending could be interrupted.

---

## Testing

### End-to-End Test:

1. **Start server:**
   ```bash
   python manage.py runserver_monitored
   ```

2. **Verify startup message:**
   ```
   Starting MONITORED Django server on 127.0.0.1:8004
   Email alerts will be sent on shutdown/crash
   ```

3. **Press Ctrl+C once**

4. **Verify terminal output:**
   ```
   Ctrl+C detected! Shutting down...
   Sending shutdown alert email...
   [OK] Email sent to 1 recipient(s):
        - your-email@example.com
   ```

5. **Check email inbox** (within 60 seconds)

### Expected Email:

- **Subject:** `[DB Sync Tool] Server Shutdown - manual_shutdown_ctrl_c`
- **From:** Your configured `DEFAULT_FROM_EMAIL`
- **Body:** Contains timestamp, server details, shutdown reason

---

## Files Involved

| File | Purpose |
|------|---------|
| `core/management/commands/runserver_monitored.py` | Main monitoring command |
| `start_server.bat` | Windows batch script wrapper |
| `core/models.py` | `NotificationRecipient` model |
| `templates/notifications.html` | Recipient management UI |
| `logs/email_errors.log` | SMTP error logging |
| `.env` | Email configuration |

---

## FAQ

**Q: Can I use plain `runserver` for development?**  
A: Yes, but you won't get email alerts. Use `runserver_monitored` if you want alerts.

**Q: Does this work on Linux/macOS?**  
A: Yes! The `KeyboardInterrupt` pattern works cross-platform.

**Q: What if SMTP is down?**  
A: Error is logged to `logs/email_errors.log` and shown in terminal. Shutdown proceeds normally.

**Q: Can I test without stopping the server?**  
A: Yes, run the SMTP test command in another terminal:
```bash
python manage.py test_email
```

**Q: How do I add more recipients?**  
A: Go to http://localhost:8004/notifications/ and add them via the UI.

---

## Quick Reference

### Start Server (Monitored):
```bash
python manage.py runserver_monitored
# or
start_server.bat
```

### Check Recipients:
```bash
python manage.py shell -c "from django.conf import settings; print(settings.ADMIN_EMAILS)"
```

### Test Email:
```bash
python manage.py test_email
```

### Check Logs:
```bash
cat logs/email_errors.log
```

### Manage Recipients UI:
```
http://localhost:8004/notifications/
```

---

**Last Updated:** 2024-05-22  
**Tested On:** Windows 11, Python 3.12, Django 4.2
