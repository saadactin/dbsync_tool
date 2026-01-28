# Debugging Step 2 Loading Issue

## Problem
Page stuck on "Loading tables..." (actually "Loading schemas...") and not proceeding.

## Quick Debugging Steps

### 1. Check Browser Console (IMPORTANT!)
1. Open browser Developer Tools (F12)
2. Go to **Console** tab
3. Look for error messages or warnings
4. Look for messages starting with:
   - `MetadataLoader:`
   - `Step 2:`
   - `Error loading schemas:`

**Share the console output** - this will tell us exactly what's happening.

### 2. Check Network Tab
1. In Developer Tools, go to **Network** tab
2. Refresh the page
3. Look for a request to `/metadata/api/[connection-id]/schemas/`
4. Check:
   - Status code (200 = success, 500 = server error, etc.)
   - Response time (how long it took)
   - Response body (what the server returned)

### 3. Check Django Server Logs
Look at the terminal where Django is running. You should see logs like:
```
INFO: Loading schemas for connection [id] ([name])
ERROR: Failed to load schemas...
```

### 4. Common Issues & Solutions

#### A. Database Connection Timeout
**Symptoms**: Request times out after 10-30 seconds

**Solutions**:
1. **Check if database is running:**
   ```bash
   # Test PostgreSQL connection
   psql -h localhost -U postgres -d test99
   ```

2. **Check connection credentials** in Connections page
3. **Verify database is accessible** from the server

#### B. Permission Issues
**Symptoms**: 403 or 401 errors in Network tab

**Solutions**:
1. Ensure you're logged in
2. Verify you have permission to access the connection
3. Check if connection belongs to your tenant

#### C. Password Decryption Error
**Symptoms**: Error message mentions "password" or "decrypt"

**Solutions**:
1. Go to Connections page
2. Edit the connection
3. Re-enter the password
4. Save and try again

#### D. Slow Database
**Symptoms**: Request takes a very long time (>30 seconds)

**Solutions**:
1. Check database server resources
2. Check network latency
3. Consider using cache (it's enabled by default)

### 5. Test Connection Directly

**Test PostgreSQL connection:**
```bash
# From command line
psql -h [HOST] -p [PORT] -U [USERNAME] -d test99
```

If this fails, the issue is with database connectivity, not the application.

### 6. Check Application Logs

**Django logs location**: Check the terminal where you ran `python manage.py runserver`

Look for:
- Connection errors
- Timeout errors
- Permission errors
- Database errors

---

## What I Just Fixed

1. ✅ **Increased timeout** from 10 to 30 seconds
2. ✅ **Added detailed console logging** - check browser console for detailed info
3. ✅ **Improved error messages** - more helpful error text
4. ✅ **Better error handling** - catches and displays errors properly

---

## Next Steps

1. **Refresh the page** (to load updated JavaScript)
2. **Open browser console** (F12 → Console tab)
3. **Try loading Step 2 again**
4. **Share the console output** - this will show exactly what's happening

---

## Temporary Workaround

If it's still not working:

1. Go back to **Step 1**
2. Try with a different connection (if available)
3. Or verify the database connection works using `psql` or another tool
4. Check if the database server is running and accessible

---

## What to Check Right Now

**In Browser Console (F12 → Console):**
- Any red error messages?
- Any messages starting with "MetadataLoader" or "Step 2"?
- What's the last message you see?

**In Network Tab (F12 → Network):**
- Is there a request to `/metadata/api/.../schemas/`?
- What's the status code?
- How long did it take?
- What's in the response?

**In Django Terminal:**
- Any error messages?
- Any logs about "Loading schemas"?
- Any database connection errors?
