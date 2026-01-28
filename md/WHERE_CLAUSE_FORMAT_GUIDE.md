# WHERE Clause Format Guide

## ✅ CORRECT Format

**What to Enter:**
```
Price > 20
```

**What NOT to Enter:**
```
SELECT * FROM public."Cakes" WHERE "Price" > 20;
```
(This is a full SQL query - DON'T use this!)

---

## 📋 Examples

### ✅ Correct Examples:

1. **Simple comparison:**
   ```
   Price > 20
   ```

2. **Multiple conditions:**
   ```
   Price > 20 AND Status = 'Active'
   ```

3. **With quotes for strings:**
   ```
   Status = 'Active' AND Category = 'Food'
   ```

4. **Date comparison:**
   ```
   CreatedAt >= '2024-01-01' AND CreatedAt < '2025-01-01'
   ```

5. **IN clause:**
   ```
   Category IN ('Food', 'Drink', 'Dessert')
   ```

6. **NULL check:**
   ```
   Email IS NOT NULL AND Email != ''
   ```

### ❌ Wrong Examples:

1. **Full SELECT statement:**
   ```
   SELECT * FROM public."Cakes" WHERE "Price" > 20;
   ```
   ❌ **WRONG** - Don't include SELECT, FROM, WHERE keywords

2. **With WHERE keyword:**
   ```
   WHERE Price > 20
   ```
   ❌ **WRONG** - Don't include the word "WHERE"

3. **With semicolon:**
   ```
   Price > 20;
   ```
   ❌ **WRONG** - Don't include semicolon

---

## 🎯 For Your Case (public.Cakes table)

**CORRECT:**
```
Price > 20
```

Or if you want multiple conditions:
```
Price > 20 AND Category = 'Cakes'
```

**That's it!** Just the condition part.

---

## 💡 What the System Does

When you enter:
```
Price > 20
```

The system automatically creates:
```sql
SELECT * FROM public."Cakes" WHERE Price > 20
```

You don't need to write the full query - just the WHERE condition!

---

## 🔍 Quick Reference

| What You Want | What to Enter |
|--------------|---------------|
| Filter by price | `Price > 20` |
| Filter by status | `Status = 'Active'` |
| Multiple conditions | `Price > 20 AND Status = 'Active'` |
| Date range | `CreatedAt >= '2024-01-01'` |
| Multiple values | `Category IN ('A', 'B', 'C')` |
| Not null | `Email IS NOT NULL` |

---

## ✅ After Fixing

The validation error should now be fixed. Try entering:
```
Price > 20
```

And click **"Validate"** - it should work now! ✨
