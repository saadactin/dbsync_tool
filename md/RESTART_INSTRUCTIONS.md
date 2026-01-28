# Restart Instructions - Step 2 Loading Fix

## ✅ All Processes Stopped

All Python/Django processes have been stopped. Ready for clean restart.

---

## 🔄 Steps to Restart

### 1. Start Django Server

```powershell
cd C:\Users\SaadSayyed\Desktop\test_proj\tauseef_sir\dbsync_tool
python manage.py runserver
```

### 2. Open Browser

- Go to: `http://localhost:8000` (or your configured port)
- Log in
- Navigate to: Create Sync Job → Step 1

### 3. Create Job in Step 1

- Enter Job Name
- Select Source Connection (pg2 or your PostgreSQL connection)
- Select Target Connection (your MySQL connection)
- Click "Next"

### 4. Step 2 - What Should Happen Now

**Expected Behavior:**
1. Page loads showing "Loading tables..." for 1-2 seconds
2. Schemas appear (e.g., "public", "dbo", etc.)
3. You can expand schemas to see tables
4. Select tables with checkboxes
5. Optionally click "⚙️ Transform" to configure transformations

**If Still Stuck:**
1. **Open Browser Console** (Press F12 → Console tab)
2. **Look for these messages:**
   ```
   Step 2: Initializing...
   Step 2: SOURCE_CONNECTION_ID = [should show UUID]
   [OK] Connection ID found: [UUID]
   Step 2: Setting up schema load...
   MetadataLoader: Loading schemas from URL: /metadata/api/[UUID]/schemas/...
   ```

3. **Check Network Tab** (F12 → Network tab)
   - Filter: XHR
   - Look for: `/metadata/api/.../schemas/`
   - Status should be: 200 (success) or error code

---

## 🔍 Debugging Checklist

### If Page Still Shows "Loading tables..." Forever:

**Check 1: Browser Console**
- Open F12 → Console
- Do you see any red errors?
- Do you see "Step 2: Initializing..." message?
- What's the last message you see?

**Check 2: Network Request**
- Open F12 → Network tab
- Filter: XHR
- Refresh the Step 2 page
- Is there a request to `/metadata/api/.../schemas/`?
- What's its status? (200, 404, 500, pending?)
- Click on it → Response tab → What does it show?

**Check 3: Django Server Terminal**
- Look at the terminal where you ran `python manage.py runserver`
- Any error messages?
- Do you see a request log like: `GET /metadata/api/.../schemas/ HTTP/1.1 200`?

**Check 4: Hard Refresh**
- Press `Ctrl + Shift + R` (hard refresh)
- Or `Ctrl + F5`
- This clears cached JavaScript files

---

## 🚨 Common Issues & Solutions

### Issue 1: "Connection ID not found"
**Solution:** Go back to Step 1 and create job again. Session might have expired.

### Issue 2: Request returns 404
**Solution:** Check URL pattern. Should be `/metadata/api/[UUID]/schemas/`

### Issue 3: Request returns 500
**Solution:** Check Django terminal for error. Usually database connection issue.

### Issue 4: Request is "pending" forever
**Solution:** 
- Database connection might be hanging
- Check if PostgreSQL is running: `pg_isready` or try connecting with psql
- Check firewall/network connectivity

### Issue 5: JavaScript not loading
**Solution:**
- Clear browser cache
- Check if static files are being served
- In Network tab, verify `create_job_step2.js` loads (status 200)

---

## ✅ What Was Fixed

1. **Multiple Load Triggers** - 3 different methods to ensure schemas load
2. **Better Error Messages** - Clear errors with retry buttons
3. **Console Logging** - Detailed logs for debugging
4. **Timeout Protection** - 30-second timeout prevents infinite hanging
5. **Element Safety** - Fixed null reference issues

---

## 📋 Quick Test After Restart

1. Start server: `python manage.py runserver`
2. Open browser: `http://localhost:8000`
3. Login
4. Create Job → Step 1 → Fill form → Next
5. Step 2 should:
   - Show "Loading tables..." for 1-2 seconds
   - Then show schemas with tables
   - Allow table selection

---

## 🆘 If Still Not Working

**Share these details:**
1. Browser console output (F12 → Console → Copy all)
2. Network request details (F12 → Network → Click on schemas request → Copy)
3. Django server terminal output (any errors?)

**Or run this test command:**
```powershell
python C:\Users\SaadSayyed\Desktop\test_proj\tauseef_sir\dbsync_tool\test_metadata_api_direct.py
```

This will test the API directly and show what's happening.

---

## 🎯 Expected Success Output (Console)

When working correctly, you should see in browser console:
```
Step 2: Initializing...
Step 2: SOURCE_CONNECTION_ID = 1dfe2e99-b5d7-4edd-80b3-b8303e1e46cc
[OK] Connection ID found: 1dfe2e99-b5d7-4edd-80b3-b8303e1e46cc
Step 2: Setting up schema load...
Step 2: DOM ready, calling loadSchemas immediately...
Step 2: loadSchemas() called, useCache= true
Step 2: All elements found, starting load...
MetadataLoader: Loading schemas from URL: /metadata/api/1dfe2e99-b5d7-4edd-80b3-b8303e1e46cc/schemas/?use_cache=true
MetadataLoader: Sending fetch request...
MetadataLoader: Fetch completed in 180ms, status: 200
MetadataLoader: Successfully loaded 1 schemas
Step 2: Schemas loaded successfully in 200ms: 1 schemas
Step 2: Displaying schemas...
Step 2: Schemas displayed successfully
```

Good luck! 🚀
