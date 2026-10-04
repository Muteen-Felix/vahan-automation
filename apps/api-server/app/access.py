from fastapi import HTTPException, Request

def owner_filter(request: Request):
    return None if request.state.authenticated_role == "admin" else request.state.authenticated_user

def require_owner(request, owner):
    if request.state.authenticated_role != "admin" and owner != request.state.authenticated_user:
        raise HTTPException(404, "Resource not found.")

def require_admin(request):
    if request.state.authenticated_role != "admin":
        raise HTTPException(403, "Administrator access required.")
