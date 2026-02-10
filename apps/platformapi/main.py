from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from pathlib import Path
import subprocess
import json
import re
from typing import List
import tempfile

app = FastAPI(title="Platform API")
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


INVENTORY_FILE = BASE_DIR / "ansible" / "inventory.yml"


def is_valid_ipv4(addr: str) -> bool:
    # Basic IPv4 validation
    if not isinstance(addr, str):
        return False
    parts = addr.split('.')
    if len(parts) != 4:
        return False
    try:
        for p in parts:
            i = int(p)
            if i < 0 or i > 255:
                return False
    except ValueError:
        return False
    return True

def parse_play_recap(output: str):
    """Parse the PLAY RECAP section from ansible-playbook stdout into a dict.

    Returns { host: {ok:int, changed:int, unreachable:int, failed:int, skipped:int, rescued:int, ignored:int}, ... }
    """
    summary = {}
    if not output:
        return summary
    m = re.search(r"PLAY RECAP \*+\n(.*?)(?:\n\n|\Z)", output, re.DOTALL)
    if not m:
        return summary
    body = m.group(1).strip()
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        # Expect lines like: host : ok=1    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        host = parts[0].strip()
        kvs = parts[1]
        stats = {}
        for kv in re.finditer(r"(\w+)=([0-9]+)", kvs):
            key = kv.group(1)
            val = int(kv.group(2))
            stats[key] = val
        summary[host] = stats
    return summary


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


@app.post("/ansible/ping")
async def ansible_ping(request: Request):
    """Run an ad-hoc Ansible ping against the provided hosts (JSON payload expected: {"hosts": ["ip1","ip2"]}).

    Falls back to DEFAULT_TARGETS when no hosts provided. Returns a JSON object with stdout/stderr/rc.
    """
    # Accept both JSON body and empty; parse JSON safely
    hosts = DEFAULT_TARGETS
    try:
        payload = await request.json()
    except Exception:
        payload = None

    if payload and isinstance(payload, dict) and "hosts" in payload:
        candidate = payload.get("hosts")
        if isinstance(candidate, list) and all(isinstance(h, str) for h in candidate):
            hosts = candidate

    # Validate hosts
    valid_hosts = [h for h in hosts if is_valid_ipv4(h)]
    if not valid_hosts:
        return {"success": False, "error": "No valid IPv4 hosts provided"}

    # Playbook path and default inventory file
    playbook_path = BASE_DIR / "ansible" / "ping.yml"
    inventory_file = BASE_DIR / "ansible" / "inventory.yml"
    if not playbook_path.exists():
        return {"success": False, "error": f"Playbook not found at {playbook_path}"}

    # If the request provided custom hosts, write a temporary inventory and use it.
    use_tmp_inventory = False
    tmp_inv = None
    try:
        if payload and isinstance(payload, dict) and "hosts" in payload:
            # Use the validated valid_hosts list to create a small inventory file
            use_tmp_inventory = True
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                tmp_inv = f.name
                for h in valid_hosts:
                    f.write(h + "\n")
            inv_path = tmp_inv
        else:
            # Default: use the static inventory.yml in the repo
            if not inventory_file.exists():
                return {"success": False, "error": f"Inventory not found at {inventory_file}"}
            inv_path = str(inventory_file)

        cmd = [
            "ansible-playbook",
            "-i",
            str(inv_path),
            str(playbook_path),
            "--user",
            "ec2-user",
            "--private-key",
            "/home/app/.ssh/id_rsa",
            "--ssh-extra-args",
            "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        play_summary = parse_play_recap(proc.stdout)
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "cmd": " ".join(cmd),
            "play_summary": play_summary,
        }
    except FileNotFoundError:
        return {"success": False, "error": "ansible-playbook binary not found in PATH. Install ansible in the container."}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Ansible command timed out"}
    finally:
        if tmp_inv:
            try:
                Path(tmp_inv).unlink()
            except Exception:
                pass
