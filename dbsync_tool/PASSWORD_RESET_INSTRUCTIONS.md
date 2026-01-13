# Password Reset Instructions

## Problem
If you see an error like "Failed to decrypt password" or "Encryption failed", it means the encryption key changed or the password data is corrupted.

## Solution

### Option 1: Update Password via Web UI (Recommended)

1. Go to **Connections** page
2. Find the connection with the error
3. Click **Edit** on that connection
4. You will see a warning that the password must be set
5. Enter the **correct password** for your database
6. Click **Save**
7. The password will be re-encrypted with the current key
8. Try using the connection again

### Option 2: Use Management Command

Run the management command to identify and fix corrupted passwords:

```bash
python manage.py fix_passwords --dry-run  # See what would be fixed
python manage.py fix_passwords            # Actually clear corrupted passwords
```

After running the command, you'll need to edit each connection and set a new password.

## Prevention

To prevent this issue:

1. **Set a fixed ENCRYPTION_KEY** in your environment variables or settings.py
2. **Never change the encryption key** after passwords are encrypted
3. **Back up your encryption key** if you need to migrate servers

## Setting a Fixed Encryption Key

1. Generate a key:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. Add to `settings.py`:
   ```python
   ENCRYPTION_KEY = 'your-generated-key-here'
   ```

3. Or set as environment variable:
   ```bash
   export ENCRYPTION_KEY='your-generated-key-here'  # Linux/Mac
   set ENCRYPTION_KEY=your-generated-key-here       # Windows
   ```

## Important Notes

- The encryption key is critical - if lost, all passwords cannot be decrypted
- Store the key securely (environment variables, secrets manager)
- In production, use environment variables, not hardcoded values

