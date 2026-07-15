"""
CI/local check: does requirements.txt contain the exact name==version pin
for every direct dependency listed in requirements.in?

This intentionally does NOT recompile requirements.in with pip-compile and
diff the full transitive closure. That approach breaks CI for reasons
unrelated to any real mistake:

  - transitive packages get new patch releases on PyPI constantly, so a
    lockfile regenerated even an hour apart from CI's run can differ
  - pip-compile resolves platform-conditional dependencies (e.g. colorama
    is Windows-only, pulled in via click) against whatever OS it runs on,
    so a lockfile committed from Windows will never exactly match what
    Linux CI recompiles - permanently, regardless of drift

Since requirements.in already hard-pins every direct dependency
(Django==4.2.13, etc.), this only checks the thing actually worth catching:
someone edited requirements.in and forgot to run `make lock` afterwards.
Run `make lock` locally when you want to actually refresh pins.
"""
import re
import sys

DIRECT_PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)(\[[^\]]+\])?==([A-Za-z0-9_.+-]+)$")


def parse_direct_pins(path):
    pins = []
    with open(path) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = DIRECT_PIN_RE.match(line)
            if match:
                name, _extras, version = match.groups()
                pins.append((name.lower(), version))
    return pins


def main():
    direct = parse_direct_pins("requirements.in")
    with open("requirements.txt") as f:
        locked = f.read().lower()

    missing = [
        f"{name}=={version}"
        for name, version in direct
        if f"{name}=={version.lower()}" not in locked
    ]

    if missing:
        print("MISMATCH - run `make lock` and commit requirements.txt:")
        for pin in missing:
            print(f"  {pin}")
        sys.exit(1)

    print("OK: all direct pins from requirements.in are present in requirements.txt")


if __name__ == "__main__":
    main()