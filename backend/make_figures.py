"""
make_figures.py: gjeneron AUTOMATIKISHT figurat 7-11 (PNG) për Shtojcën D të punimit.

Një komandë, pa print screen dorazi:
    python make_figures.py              (të gjitha figurat 7-11)
    python make_figures.py 7 8 9        (vetëm figurat nga API-ja)
    python make_figures.py 10 11        (vetëm auditimi statik dhe testi dinamik)

Çfarë bën:
    Fig. 7-9   thërret API-në reale (api_evidence.py), 2 login gjithsej, dhe vizaton daljen
    Fig. 10    ekzekuton auditimin statik check_tenant_isolation.py
    Fig. 11    ekzekuton testin dinamik dynamic_tenant_isolation_test
Imazhet ruhen te bizal\\evidence\\ (300 dpi) së bashku me daljen e papërpunuar (raw_output.txt) dhe
raportin JSONL të testit dinamik. Çdo imazh ka komandën, datën dhe orën e ekzekutimit.

Kërkesa: Python i venv-it të projektit (ka requests, Pillow, Django). Fig. 10-11 duan Django.
"""
import datetime
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
OUT = HERE.parent / "evidence"

try:
    from PIL import Image, ImageDraw, ImageFont  # noqa: E402
except ImportError:
    sys.exit("Mungon Pillow. Përdor Python-in e venv-it (PowerShell: ..\\venv\\Scripts\\python make_figures.py) "
             "ose instalo: pip install pillow   (WSL: sudo apt install python3-pil)")

import api_evidence as ev  # noqa: E402


# ── Vizatimi i daljes së komandës ────────────────────────────────────────────
# Cilësia: imazhi vizatohet drejtpërdrejt në rezolucion të lartë (SCALE x) dhe ruhet me 300 dpi.
# Të gjitha figurat kanë të njëjtën gjerësi në karaktere (COLS), kështu që kur futen në Word me
# të njëjtën gjerësi faqeje, shkronjat dalin me të njëjtën madhësi në çdo figurë.
SCALE = 3          # 3x rezolucion (imazh ~2700 px i gjerë)
FONT_PT = 15       # madhësia logjike e shkronjës
COLS = 92          # gjerësia fikse e figurës, në karaktere
FONT_CANDIDATES = {
    False: [r"C:\Windows\Fonts\consola.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/System/Library/Fonts/Menlo.ttc", "DejaVuSansMono.ttf"],
    True: [r"C:\Windows\Fonts\consolab.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
           "/System/Library/Fonts/Menlo.ttc", "DejaVuSansMono-Bold.ttf"],
}


def load_font(bold, size):
    for path in FONT_CANDIDATES[bold]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def scrub(text):
    """Heq shtigjet lokale dhe emrin e përdoruesit nga çdo tekst që del në figurë ose në raw_output."""
    text = text.replace(str(HERE), r"...\bizal\backend").replace(str(HERE.parent), r"...\bizal")
    text = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", "...", text)          # C:\Users\<emri>
    text = re.sub(r"/(?:home|Users)/[^/\s]+", "...", text)              # /home/<emri>, /Users/<emri>
    text = re.sub(r"(?:\.\.\.\\)?(?:[\w.\-]+\\)*tenant_isolation_report\.jsonl", "tenant_isolation_report.jsonl", text)
    return text


def normalize(text):
    """Rrjetë sigurie: emërtim i njëjtë me tekstin e punimit, edhe nëse dalja e testit është e vjetër."""
    text = text.replace("Tested (SAFE — correctly rejected):", "Tested (NO-LEAK, correctly rejected):")
    text = text.replace("(live DB, real requests)", "(sqlite test DB, real requests)")
    return text


def line_style(line):
    """Kthen (ngjyra, e trashë) për një rresht, sipas përmbajtjes."""
    s = line.strip()
    if s.startswith("===="):
        return "#98a2b3", False
    if re.match(r"^\[\d+\]", s):
        return "#0b3d91", True
    if s.startswith("-> HTTP 2"):
        return "#0a7d33", True
    if s.startswith("-> HTTP 4") or s.startswith("-> HTTP 5"):
        return "#b3261e", True
    if s.startswith("RESULT: PASS") or s.startswith("[SAFE]") or re.match(r"^LEAKS:\s+0\b", s):
        return "#0a7d33", True
    if s.startswith("RESULT: FAIL") or re.match(r"^LEAKS:\s+[1-9]", s):
        return "#b3261e", True
    if s.startswith("[") and "allowlisted" in s:
        return "#0b3d91", True
    return "#1f2933", False


def wrap_line(line, cols):
    """Thyen rreshtat e gjatë (me shtypje të njëjtë vazhdimi), që figura të mos zgjerohet."""
    if len(line) <= cols:
        return [line]
    indent = len(line) - len(line.lstrip())
    parts = textwrap.wrap(line, width=cols, subsequent_indent=" " * (indent + 4),
                          break_long_words=True, break_on_hyphens=False)
    return parts or [line]


def render(lines, command, footer, path):
    S = SCALE
    fs = FONT_PT * S
    reg, bold = load_font(False, fs), load_font(True, fs)
    small = load_font(False, int(fs * 0.78))
    cw = reg.getlength("M")                      # gjerësia e një karakteri (monospace)
    lh = int(fs * 1.55)
    pad, bar, foot_lh = 26 * S, 46 * S, int(fs * 1.25)

    lines = [ln for raw in lines for ln in wrap_line(normalize(scrub(raw)).rstrip(), COLS)]
    command = scrub(command)
    # footer: thyhet sipas gjerësisë reale, deri në 3 rreshta
    width = int(COLS * cw + 2 * pad)
    words, foot_lines, cur = scrub(footer).split(" "), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if small.getlength(trial) > width - 2 * pad and cur:
            foot_lines.append(cur)
            cur = w
        else:
            cur = trial
    foot_lines.append(cur)
    foot = pad // 2 + foot_lh * len(foot_lines) + pad // 2
    height = bar + pad + lh * len(lines) + pad // 2 + foot

    img = Image.new("RGB", (width, height), "#f6f8fa")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, bar], fill="#e4e7ec")
    d.text((pad, bar // 2), "$ " + command, font=reg, fill="#344054", anchor="lm")
    tag = "RIPRODHIM I DALJES"
    d.text((width - pad, bar // 2), tag, font=small, fill="#667085", anchor="rm")

    y = bar + pad
    for ln in lines:                              # çdo karakter në rrjetën e vet: shtylla gjithmonë në vijë
        color, is_bold = line_style(ln)
        font = bold if is_bold else reg
        for i, ch in enumerate(ln):
            if ch != " ":
                d.text((pad + i * cw, y), ch, font=font, fill=color)
        y += lh
    fy = height - foot
    d.line([pad, fy, width - pad, fy], fill="#d0d5dd", width=max(1, S // 2))
    ty = fy + pad // 2
    for fl in foot_lines:
        d.text((pad, ty), fl, font=small, fill="#667085")
        ty += foot_lh
    d.rectangle([0, 0, width - 1, height - 1], outline="#d0d5dd", width=S // 2 or 1)
    img.save(path, dpi=(300, 300), optimize=True)


# ── Komandat ndihmëse ────────────────────────────────────────────────────────
def run(cmd, env_extra=None, drop=()):
    env = os.environ.copy()
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    env.update(env_extra or {})
    for k in drop:
        env.pop(k, None)
    p = subprocess.run(cmd, cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return p.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")


def has_django():
    return subprocess.run([sys.executable, "-c", "import django"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# Testi dinamik ekzekutohet me SQLite në memorie (bizal.settings.test). Kodi i platformës ka disa
# komanda `SET LOCAL lock_timeout` që ekzistojnë vetëm në PostgreSQL dhe SQLite i refuzon.
# Këtu ato anashkalohen (zëvendësohen me SELECT 1) vetëm gjatë këtij ekzekutimi, pa ndryshuar
# kodin e projektit. Komanda kufizon vetëm kohën e pritjes së bllokimeve; nuk ndikon në
# leje apo filtrim sipas tenant-it, që është ajo që provon ky test.
DYNAMIC_RUNNER = """
import os, sys
os.environ["DJANGO_SETTINGS_MODULE"] = "bizal.settings.test"
import django
django.setup()
from django.db.backends.sqlite3 import base
_orig = base.SQLiteCursorWrapper.execute
def _execute(self, query, params=None):
    if isinstance(query, str) and query.lstrip().upper().startswith("SET LOCAL"):
        query = "SELECT 1"
    return _orig(self, query, params)
base.SQLiteCursorWrapper.execute = _execute
from django.core.management import call_command
call_command("test", "bizal.tests.dynamic_tenant_isolation_test", verbosity=1)
"""

# ── Figurat ──────────────────────────────────────────────────────────────────
def api_figures(wanted, raw):
    blocks, meta = ev.collect()
    where = meta["base"] + (f" (Host: <slug>.{meta['main_domain']})" if meta["mode"] == "host" else "")
    footer = f"{meta['time']}  |  {where}  |  riprodhim i daljes reale të komandës, gjeneruar nga make_figures.py"
    groups = {7: ([1, 2, 3], "python api_evidence.py 1-3"),
              8: ([4, 5, 6], "python api_evidence.py 4-6"),
              9: ([7], "python api_evidence.py 7")}
    raw.append("### API (api_evidence.py), " + footer + "\n" + "\n".join(blocks[k] for k in range(1, 8)))
    for fig in (7, 8, 9):
        if fig not in wanted:
            continue
        steps, cmd = groups[fig]
        lines = "\n".join(blocks[k] for k in steps).splitlines() + ["=" * 72]
        render(lines, cmd, footer, OUT / f"fig{fig}.png")
        print(f"  ✓ fig{fig}.png")


def audit_figure(raw):
    cmd = [sys.executable, str(Path("bizal") / "tests" / "check_tenant_isolation.py")]
    txt = run(cmd)
    keep = [l for l in txt.splitlines() if re.match(r"^(Scanned|\[|RESULT)", l)]
    if not keep:
        print("  ✗ fig10: dalja e auditimit statik nuk u njoh:\n" + txt[-600:])
        return
    if "RESULT: FAIL" in txt:
        print("  ! KUJDES: auditimi statik dha FAIL. Mos e përdor këtë figurë; kontrollo tenant_isolation_allowlist.py "
              "dhe rreshtat me 'NOT ALLOWLISTED' më poshtë.\n" + "\n".join(l for l in txt.splitlines() if "NOT ALLOWLISTED" in l))
    footer = f"{now()}  |  analizë statike (AST), pa bazë të dhënash  |  riprodhim i daljes reale të komandës, gjeneruar nga make_figures.py"
    render(keep, "python bizal/tests/check_tenant_isolation.py", footer, OUT / "fig10.png")
    raw.append("### Auditimi statik\n" + txt)
    print("  ✓ fig10.png")


def dynamic_figure(raw):
    print("  … duke ekzekutuar testin dinamik (mund të zgjasë një minutë)")
    report = "tenant_isolation_report.jsonl"
    txt = run([sys.executable, "-c", DYNAMIC_RUNNER],
              env_extra={"DJANGO_SETTINGS_MODULE": "bizal.settings.test", "ISOLATION_REPORT_PATH": report},
              drop=("CI",))
    lines = txt.splitlines()
    try:
        i = next(k for k, l in enumerate(lines) if "DYNAMIC cross-tenant isolation probe" in l)
        j = next(k for k in range(i, len(lines)) if lines[k].startswith("LEAKS:"))
    except StopIteration:
        print("  ✗ fig11: blloku i përmbledhjes nuk u gjet. Fundi i daljes:\n" + txt[-800:])
        return
    start = i - 1 if i > 0 and lines[i - 1].startswith("===") else i
    footer = (f"{now()}  |  settings: bizal.settings.test, SQLite në memorie (jo baza reale e prodhimit; "
              "komandat PostgreSQL SET LOCAL anashkalohen)  |  "
              "riprodhim i daljes reale të komandës, gjeneruar nga make_figures.py")
    render(lines[start:j + 1], "python manage.py test bizal.tests.dynamic_tenant_isolation_test",
           footer, OUT / "fig11.png")
    raw.append("### Testi dinamik\n" + txt)
    src = HERE / report
    if src.exists():
        shutil.move(str(src), str(OUT / report))
    print("  ✓ fig11.png  (+ raporti JSONL)")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    wanted = {int(a) for a in sys.argv[1:]} or {7, 8, 9, 10, 11}
    OUT.mkdir(exist_ok=True)
    raw = []
    print(f"Figurat ruhen te: {OUT}")
    if wanted & {7, 8, 9}:
        api_figures(wanted, raw)
    if wanted & {10, 11}:
        if not has_django():
            print("  ✗ fig10/11 kërkojnë Django. Ekzekuto me Python të venv-it të projektit "
                  "(PowerShell: ..\\venv\\Scripts\\python make_figures.py 10 11).")
        else:
            if 10 in wanted:
                audit_figure(raw)
            if 11 in wanted:
                dynamic_figure(raw)
    if raw:
        (OUT / "raw_output.txt").write_text(scrub("\n\n".join(raw)), encoding="utf-8")
    print("Gati. Ngarkoji imazhet fig7.png ... fig11.png këtu në bisedë.")


if __name__ == "__main__":
    main()