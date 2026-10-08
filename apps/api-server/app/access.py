from fastapi import HTTPException, Request


def member_api_allowed(method: str, path: str) -> bool:
    """Members can read/export reports and manage their own login only."""
    path = path.rstrip('/')
    if method == 'GET':
        return path in {'/api/auth/me', '/api/user-state', '/api/network/status', '/api/annual-reports',
                        '/api/annual-reports/history', '/api/annual-reports/export',
                        '/api/annual-reports/update-status'}
    if method == 'POST':
        return path in {'/api/auth/logout', '/api/auth/activity', '/api/auth/password',
                        '/api/annual-reports/coverage'}
    return False

def owner_filter(request: Request):
    return None if request.state.authenticated_role == "admin" else request.state.authenticated_user

def require_owner(request, owner):
    if request.state.authenticated_role != "admin" and owner != request.state.authenticated_user:
        raise HTTPException(404, "Resource not found.")

def require_admin(request: Request):
    if request.state.authenticated_role != "admin":
        raise HTTPException(403, "Administrator access required.")
