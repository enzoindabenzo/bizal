"""
api_evidence.py: demonstron izolimin e të dhënave përmes API-t (dalje për Shtojcën D të punimit).

Përdorimi:
    python api_evidence.py            (të gjithë hapat 1-7)
    python api_evidence.py 4-6        (vetëm disa hapa; kërkesat ekzekutohen gjithsesi)

Serveri gjendet automatikisht:
    1) http://localhost        (stack-u Docker prod me nginx, tenant përmes header-it Host)
    2) http://localhost:8001   (dev.py ose Docker dev, tenant përmes ?tenant=<slug>)
Për ta detyruar: BIZAL_BASE, BIZAL_TENANT_MODE ("host" ose "query"), BIZAL_MAIN_DOMAIN.

Fjalëkalimet lexohen nga .env.seed (bizal\\.env.seed ose backend\\.env.seed) dhe nuk printohen.
Skripti vetëm LEXON të dhënat demonstruese; nuk krijon dhe nuk fshin asgjë.
"""
import datetime
import getpass
import json
import os
import sys
from pathlib import Path

import requests

MAIN_DOMAIN = os.environ.get("BIZAL_MAIN_DOMAIN", "bizal.al")
BASE = os.environ.get("BIZAL_BASE")
MODE = os.environ.get("BIZAL_TENANT_MODE", "").lower()

# A = biznesi "viktimë" (ka faturë demonstruese), B = biznesi tjetër që tenton akses.
TENANT_A, OWNER_A, KEY_A = "hertz-albania",       "owner@hertz.al",     "SEED_OWNER_PASSWORD_CARS"
TENANT_B, OWNER_B, KEY_B = "restorant-adriatiku", "owner@adriatiku.al", "SEED_OWNER_PASSWORD_RESTO"


# ── Fjalëkalimet nga .env.seed ───────────────────────────────────────────────
def load_seed_files():
    here = Path(__file__).resolve().parent
    found, seen = [], set()
    for d in (here.parent, here, Path.cwd(), Path.cwd().parent):
        f = d / ".env.seed"
        if f.exists() and f.resolve() not in seen:
            seen.add(f.resolve())
            out = {}
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    out[k.strip()] = v.strip()
            found.append(out)
    return found


SEED_FILES = load_seed_files()


# ── Kërkesat HTTP ────────────────────────────────────────────────────────────
def call(method, path, tenant, token=None, body=None, timeout=30):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"{BASE}{path}"
    if MODE == "host":
        headers["Host"] = f"{tenant}.{MAIN_DOMAIN}"
    else:
        url += ("&" if "?" in path else "?") + f"tenant={tenant}"
    return requests.request(method, url, headers=headers, json=body, timeout=timeout)


def configure():
    """Vendos BASE dhe MODE: nga variablat e mjedisit, ose duke provuar serverat e njohur."""
    global BASE, MODE
    if BASE:
        MODE = MODE or "query"
        return
    for base, mode in (("http://localhost", "host"), ("http://localhost:8001", "query")):
        BASE, MODE = base, mode
        try:
            r = call("GET", "/api/tenants/info/", TENANT_A, timeout=5)
            if r.status_code == 200 and r.json().get("slug") == TENANT_A:
                return
        except (requests.RequestException, ValueError):
            pass
    BASE = None
    sys.exit("Serveri nuk përgjigjet as te http://localhost as te http://localhost:8001.\n"
             "Ndize stack-un (Docker: docker compose -f docker-compose.prod.yml up -d, "
             "ose: python dev.py) dhe provo përsëri.")


def try_login(tenant, email, pw):
    r = call("POST", "/api/auth/login/", tenant, body={"email": email, "password": pw})
    if r.status_code in (403, 429):
        sys.exit("Login u bllokua nga kufizimi i kërkesave (5 login në minutë).\n"
                 "Prit 1 minutë dhe ekzekuto vetëm një herë.")
    return r.json()["access"] if r.status_code == 200 else None


def login(tenant, email, key):
    candidates = []
    for pw in [os.environ.get(key)] + [f.get(key) for f in SEED_FILES]:
        if pw and pw not in candidates:
            candidates.append(pw)
    for pw in candidates:
        token = try_login(tenant, email, pw)
        if token:
            return token
    pw = getpass.getpass(f"Fjalëkalimi i {email} (nuk u gjet te .env.seed): ")
    token = try_login(tenant, email, pw)
    if not token:
        sys.exit(f"Login dështoi për {email}. Kontrollo fjalëkalimin.")
    return token


# ── Formatimi i një hapi ─────────────────────────────────────────────────────
def block(step, title, method, path, tenant, who, r, keep=None, item_keys=None, max_items=2):
    try:
        data = r.json()
    except ValueError:
        data = r.text[:200]
    if keep and isinstance(data, dict):
        data = {k: data[k] for k in keep if k in data}
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        data = dict(data)
        data["results"] = data["results"][:max_items]
        if item_keys:
            data["results"] = [{k: it.get(k) for k in item_keys} for it in data["results"]]
    body = json.dumps(data, ensure_ascii=False, indent=2)
    lines = [
        "=" * 72,
        f"[{step}] {title}",
        f"    {method} {path}",
        f"    portali: {tenant}   token: {who}",
        f"    -> HTTP {r.status_code} {r.reason}",
    ] + ["    " + ln for ln in body.splitlines()][:24]
    return "\n".join(lines)


def collect():
    """Ekzekuton të gjitha kërkesat një herë (2 login) dhe kthen ({hapi: tekst}, meta)."""
    configure()
    tok_a = login(TENANT_A, OWNER_A, KEY_A)
    tok_b = login(TENANT_B, OWNER_B, KEY_B)
    inv_keys = ["invoice_number", "status", "customer_name"]
    out = {}

    r = call("GET", "/api/tenants/info/", TENANT_A)
    out[1] = block(1, "PUBLIC: info e biznesit A, pa login", "GET", "/api/tenants/info/",
                   TENANT_A, "asnjë", r, keep=["name", "slug", "business_type", "city"])

    r = call("GET", "/api/billing/invoices/", TENANT_A, tok_a)
    out[2] = block(2, "Pronari A liston faturat e biznesit të vet", "GET", "/api/billing/invoices/",
                   TENANT_A, "A", r, keep=["count", "results"], item_keys=inv_keys)
    items = r.json().get("results", []) if r.status_code == 200 else []
    if not items:
        sys.exit("Biznesi A nuk ka faturë demonstruese (seed.py nuk e krijoi INV-001).")
    path = f"/api/billing/invoices/{items[0]['id']}/"

    r = call("GET", path, TENANT_A, tok_a)
    out[3] = block(3, "Pronari A merr një faturë të vetën", "GET", path, TENANT_A, "A", r,
                   keep=["id", "invoice_number", "status"])

    r = call("GET", path, TENANT_A, tok_b)
    out[4] = block(4, "Pronari B kërkon faturën e A-së (duhet të refuzohet)", "GET", path,
                   TENANT_A, "B", r)

    r = call("PATCH", path, TENANT_A, tok_b, body={"notes": "tentativë e paautorizuar"})
    out[5] = block(5, "Pronari B tenton ta ndryshojë faturën e A-së (PATCH)", "PATCH", path,
                   TENANT_A, "B", r)

    r = call("GET", "/api/billing/invoices/", TENANT_A, tok_b)
    out[6] = block(6, "Pronari B liston faturat te portali i A-së", "GET", "/api/billing/invoices/",
                   TENANT_A, "B", r)

    r = call("GET", "/api/billing/invoices/", TENANT_A)
    out[7] = block(7, "Pa token fare (endpoint i mbrojtur)", "GET", "/api/billing/invoices/",
                   TENANT_A, "asnjë", r)

    meta = {"base": BASE, "mode": MODE, "main_domain": MAIN_DOMAIN,
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    return out, meta


def parse_steps(arg):
    """'1-3' -> {1,2,3}; '4,6' -> {4,6}; None -> të gjithë."""
    if not arg:
        return set(range(1, 8))
    out = set()
    for part in arg.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    selected = parse_steps(sys.argv[1] if len(sys.argv) > 1 else None)
    blocks, meta = collect()
    for step in sorted(selected):
        if step in blocks:
            print(blocks[step])
    print("=" * 72)
    where = meta["base"] + (f"  (Host: <slug>.{meta['main_domain']})" if meta["mode"] == "host" else "")
    print(f"{meta['time']}   {where}")


if __name__ == "__main__":
    main()