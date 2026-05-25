# Email Monitoring - Complete User Guide

## ✅ SOLUTION: Use the Batch Script or the `runserver_monitored` Command

The standard `python manage.py runserver` does NOT have email monitoring.  
To get email alerts on shutdown, you have **two easy options**:

---

## Option 1: Batch Script (EASIEST - Recommended)

### Double-Click `start_server.bat`

That's it! The batch script automatically:
- Starts the server with email monitoring
- Uses port 8004 by default
- Shows clear messages when email is sent
- Pauses after shutdown so you can read the output

### Custom Port:
```bash
start_server.bat 8000
```

---

## Option 2: Manual Command

### Start with Email Monitoring:
```bash
cd dbsync_tool
python manage.py runserver_monitored
```

###With Custom Port:
```bash
python manage.py runserver_monitored --port 8000
```

---

## ❌ What NOT to Do

### This will NOT send emails:
```bash
python manage.py runserver 8004
```

The plain `runserver` command has no email hooks. You MUST use one of the options above.

---

## 📺 What You'll See

### On Startup:
```
======================================================================
  Django Server (EMAIL MONITORING ENABLED)
  Server: http://127.0.0.1:8004/
  Email will be sent on shutdown/crash
======================================================================

Watching for file changes with StatReloader
Starting development server at http://127.0.0.1:8004/
```

### When You Press Ctrl+C:
```
^C
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

## 📧 Email You'll Receive

```
From: saadpractice4@gmail.com
To: saad.sayyed@actin.co.in
Subject: [DB Sync Tool] Server Shutdown - manual_shutdown_ctrl_c

Server Shutdown Notification
============================================================

Project: DB Sync Tool
Server: 127.0.0.1:8004
Timestamp: 2024-05-22 15:30:15
Reason: manual_shutdown_ctrl_c

============================================================
```

---

## 🎯 Quick Reference

| What You Want | Command |
|---------------|---------|
| Start with monitoring (default port 8004) | Double-click `start_server.bat` |
| Start with monitoring (custom port) | `start_server.bat 8000` |
| Start manually | `python manage.py runserver_monitored` |
| Add/remove email recipients | Go to http://localhost:8004/notifications/ |
| Test if SMTP works | `python manage.py test_email` |

---

## ⚙️ Configuration

### Email Recipients

Emails are sent to:
1. **Active recipients from database** - Manage at `/notifications/`
2. **Fallback: ADMIN_EMAILS from .env**

Currently configured:
- `saad.sayyed@actin.co.in` (from .env)

### Add More Recipients:

Visit: **http://localhost:8004/notifications/**
- Click "Add Recipient"
- Enter email and optional name
- Click "Add"

---

## 🐛 Troubleshooting

### No Email Received?

**1. Check which command you used:**
```bash
# Wrong (no monitoring):
python manage.py runserver 8004

# Correct (with monitoring):
python manage.py runserver_monitored
# OR
start_server.bat
```

**2. Check terminal output:**

Did you see this message?
```
[OK] Email sent to 1 recipient(s):
     - saad.sayyed@actin.co.in
```

- **YES** → Email was sent, check spam folder
- **NO** → Check `logs/email_errors.log`

**3. Test SMTP independently:**
```bash
cd dbsync_tool
python manage.py shell -c "
from django.core.mail import send_mail
from django.conf import settings
send_mail('Test', 'Test message', settings.DEFAULT_FROM_EMAIL, settings.ADMIN_EMAILS)
print('Email sent!')
"
```

**4. Verify recipients:**
```bash
python manage.py shell -c "from django.conf import settings; print(settings.ADMIN_EMAILS)"
```

Should output: `['saad.sayyed@actin.co.in']`

---

## 📁 Files Reference

| File | Purpose |
|------|---------|
| `start_server.bat` | Windows batch script (EASIEST way to start) |
| `core/management/commands/runserver_monitored.py` | The monitoring command |
| `/notifications/` | Web UI to manage email recipients |
| `logs/email_errors.log` | SMTP error logging |
| `.env` | Email configuration (SMTP settings) |

---

## 💡 Tips

1. **Always use the batch script** - It's the easiest and you won't forget
2. **Add team emails** at `/notifications/` page
3. **Test it once** - Run `start_server.bat`, wait 5 seconds, press Ctrl+C, check email
4. **Bookmark this guide** - Keep it handy for reference

---

##Summary

✅ **To start server with email monitoring:**
- **Easiest:** Double-click `start_server.bat`
- **Manual:** `python manage.py runserver_monitored`

❌ **This will NOT work:**
- `python manage.py runserver 8004` (plain command, no monitoring)

📧 **Email will arrive within 60 seconds of pressing Ctrl+C**

---

**Questions? Check:**
- `SERVER_MONITORING_GUIDE.md` - Full technical documentation
- `CRITICAL_BUG_FIX_FINAL.md` - Implementation details
- `logs/email_errors.log` - SMTP error logs

**Last Updated:** 2024-05-22
