# API Development Guide

## Overview

This guide explains how to create API endpoints in the DB Sync Tool project without encountering CSRF or authentication issues.

---

## ✅ ALWAYS Use `@api_view` Decorator

**Location:** `core/decorators.py`

### Why?

The `@api_view` decorator handles:
- ✅ **CSRF exemption** (API endpoints use session-based auth, not CSRF tokens)
- ✅ **Authentication** (requires login by default)
- ✅ **Method validation** (only allowed HTTP methods work)
- ✅ **JSON parsing** (automatically parses request body)
- ✅ **Consistent error responses** (standard format)

### Basic Usage

```python
from core.decorators import api_view, json_response

@api_view(methods=['GET'])
@json_response
def my_api_endpoint(request):
    """Your API endpoint"""
    data = {'message': 'Hello World'}
    return {'success': True, 'data': data}
```

---

## Examples

### GET Request (List Data)

```python
@api_view(methods=['GET'])
@json_response
def list_items(request):
    """List all items"""
    items = Item.objects.all()
    data = [{'id': i.id, 'name': i.name} for i in items]
    return {'success': True, 'data': data}
```

### POST Request (Create Data)

```python
@api_view(methods=['POST'])
@json_response
def create_item(request):
    """Create a new item"""
    # request.json_data is automatically parsed from request body
    name = request.json_data.get('name')
    
    if not name:
        raise ValueError('Name is required')
    
    item = Item.objects.create(name=name)
    
    return {
        'success': True,
        'message': 'Item created',
        'data': {'id': item.id, 'name': item.name}
    }
```

### PATCH Request (Update Data)

```python
@api_view(methods=['PATCH'])
@json_response
def update_item(request, item_id):
    """Update an existing item"""
    try:
        item = Item.objects.get(id=item_id)
    except Item.DoesNotExist:
        raise ValueError('Item not found')
    
    # Update fields
    if request.json_data.get('name'):
        item.name = request.json_data['name']
        item.save()
    
    return {
        'success': True,
        'message': 'Item updated',
        'data': {'id': item.id, 'name': item.name}
    }
```

### DELETE Request (Delete Data)

```python
@api_view(methods=['DELETE'])
@json_response
def delete_item(request, item_id):
    """Delete an item"""
    try:
        item = Item.objects.get(id=item_id)
    except Item.DoesNotExist:
        raise ValueError('Item not found')
    
    item.delete()
    
    return {
        'success': True,
        'message': 'Item deleted'
    }
```

### Multiple Methods

```python
@api_view(methods=['GET', 'POST'])
@json_response
def items_endpoint(request):
    """Handle both GET and POST"""
    if request.method == 'GET':
        items = Item.objects.all()
        return {'success': True, 'data': list(items.values())}
    
    elif request.method == 'POST':
        name = request.json_data.get('name')
        item = Item.objects.create(name=name)
        return {'success': True, 'data': {'id': item.id}}
```

---

## Error Handling

The `@json_response` decorator automatically catches exceptions:

```python
@api_view(methods=['POST'])
@json_response
def create_item(request):
    # Raise ValueError for 400 Bad Request
    if not request.json_data.get('name'):
        raise ValueError('Name is required')
    
    # Raise PermissionError for 403 Forbidden
    if not request.user.is_staff:
        raise PermissionError('Staff only')
    
    # Any other exception = 500 Internal Server Error
    item = Item.objects.create(name=request.json_data['name'])
    return {'success': True}
```

**Error Response Format:**

```json
{
    "success": false,
    "error": "Name is required"
}
```

---

## Frontend JavaScript

**Always include `Content-Type: application/json` header:**

```javascript
// GET request
const response = await fetch('/api/items/', {
    method: 'GET',
    headers: {
        'Content-Type': 'application/json'
    }
});

// POST request
const response = await fetch('/api/items/create/', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken()  // Not needed with @api_view
    },
    body: JSON.stringify({name: 'New Item'})
});

// PATCH request
const response = await fetch('/api/items/1/update/', {
    method: 'PATCH',
    headers: {
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({name: 'Updated Name'})
});

// DELETE request
const response = await fetch('/api/items/1/delete/', {
    method: 'DELETE',
    headers: {
        'Content-Type': 'application/json'
    }
});
```

---

## Parameters

### `@api_view(methods, require_auth)`

- **`methods`**: List of allowed HTTP methods (default: all methods allowed)
  - Example: `methods=['GET', 'POST']`

- **`require_auth`**: Require authentication (default: `True`)
  - Set to `False` for public endpoints (rare)
  - Example: `@api_view(methods=['GET'], require_auth=False)`

---

## Available Request Attributes

When using `@api_view`, you get:

- **`request.json_data`**: Parsed JSON from request body (POST/PUT/PATCH only)
- **`request.user`**: Authenticated user object
- **`request.method`**: HTTP method (GET, POST, etc.)
- **`request.GET`**: Query parameters
- **`request.POST`**: Form data (if not JSON)

---

## ❌ DON'T Do This (Old Way)

```python
# ❌ WRONG - Manual CSRF handling
@login_required
@csrf_exempt
@require_http_methods(["POST"])
def create_item(request):
    try:
        data = json.loads(request.body)
        # ... lots of boilerplate code
        return JsonResponse({'success': True}, status=200)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
```

## ✅ DO This (New Way)

```python
# ✅ CORRECT - Clean and simple
@api_view(methods=['POST'])
@json_response
def create_item(request):
    data = request.json_data  # Already parsed!
    item = Item.objects.create(**data)
    return {'success': True, 'data': {'id': item.id}}
```

---

## Migration Guide

To convert existing API endpoints:

1. **Import the decorators:**
   ```python
   from core.decorators import api_view, json_response
   ```

2. **Replace old decorators:**
   ```python
   # OLD:
   @login_required
   @csrf_exempt
   @require_http_methods(["POST"])
   
   # NEW:
   @api_view(methods=['POST'])
   @json_response
   ```

3. **Simplify the function:**
   - Remove `try/except` blocks (handled by `@json_response`)
   - Use `request.json_data` instead of `json.loads(request.body)`
   - Return dict instead of `JsonResponse`
   - Raise `ValueError` for bad requests

4. **Update frontend:**
   - Add `'Content-Type': 'application/json'` header
   - Remove `'X-CSRFToken'` (not needed anymore)

---

## Summary

**Golden Rules:**

1. ✅ **Always use `@api_view` for API endpoints**
2. ✅ **Always use `@json_response` for automatic error handling**
3. ✅ **Always send `Content-Type: application/json` from frontend**
4. ✅ **Return dict, not JsonResponse** (decorator handles it)
5. ✅ **Raise ValueError for bad requests** (automatic 400 response)

**Result:** No more CSRF issues, cleaner code, consistent API responses!

---

**Last Updated:** 2026-05-22
