"""
Custom decorators for views
"""
from functools import wraps
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
import json


def api_view(methods=None, require_auth=True):
    """
    Decorator for API views that handles:
    - CSRF exemption (API endpoints use token-based auth)
    - Authentication requirement
    - Method validation
    - JSON body parsing
    - Consistent error responses

    Usage:
        @api_view(methods=['POST', 'PATCH'], require_auth=True)
        def my_api_view(request, **kwargs):
            # request.json_data available if request has JSON body
            return JsonResponse({'success': True})
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            # Validate HTTP method
            if methods and request.method not in methods:
                return JsonResponse({
                    'success': False,
                    'error': f'Method not allowed. Allowed: {", ".join(methods)}'
                }, status=405)

            # Parse JSON body if present
            if request.method in ['POST', 'PUT', 'PATCH'] and request.body:
                try:
                    content_type = request.META.get('CONTENT_TYPE', '')
                    if 'application/json' in content_type:
                        request.json_data = json.loads(request.body.decode('utf-8'))
                    else:
                        request.json_data = None
                except json.JSONDecodeError:
                    return JsonResponse({
                        'success': False,
                        'error': 'Invalid JSON in request body'
                    }, status=400)
            else:
                request.json_data = None

            # Call the actual view
            return view_func(request, *args, **kwargs)

        # Apply decorators in correct order
        if require_auth:
            wrapped_view = login_required(wrapped_view)

        # CSRF exempt for all API endpoints (they're protected by login_required + session auth)
        wrapped_view = csrf_exempt(wrapped_view)

        return wrapped_view

    return decorator


def json_response(view_func):
    """
    Decorator that catches exceptions and returns JSON responses.

    Usage:
        @json_response
        def my_view(request):
            if error:
                raise ValueError("Something went wrong")
            return {'success': True, 'data': [...]}
    """
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        try:
            result = view_func(request, *args, **kwargs)

            # If view returns dict, convert to JsonResponse
            if isinstance(result, dict):
                return JsonResponse(result)

            # If view already returns HttpResponse, return as-is
            return result

        except ValueError as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        except PermissionError as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=403)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Unexpected error in {view_func.__name__}: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': 'Internal server error'
            }, status=500)

    return wrapped_view
