from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from pathlib import Path

app = FastAPI(title="Platform API")
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
async def get_login(request: Request) -> HTMLResponse:
    """Render the login template."""
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None, "message": None, "url_for": request.url_for},
    )


@app.post("/login", name="login", response_class=HTMLResponse)
async def do_login(request: Request, username: str = Form(...), password: str = Form(...)) -> HTMLResponse:
    """Authenticate with a hard-coded admin/admin credential (demo only)."""
    if username == "admin" and password == "admin":
        # Redirect to the main app/dashboard on successful login
        return RedirectResponse(url=request.url_for("app_home"), status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid credentials", "message": None, "url_for": request.url_for},
        status_code=401,
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/app", name="app_home", response_class=HTMLResponse)
async def app_home(request: Request) -> HTMLResponse:
    """Render a simple dashboard/main page with API information."""
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "Platform API",
            "health_url": request.url_for("health"),
            "endpoints": ["/", "/login", "/health"],
        },
    )
