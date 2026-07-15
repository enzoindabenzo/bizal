"""
BizAL — shared field validators.
"""
import re
from django.core.exceptions import ValidationError

# Allowed image formats as reported by Pillow's Image.format.
# imghdr was deprecated in Python 3.11 and removed in Python 3.13, so
# we use Pillow (already a Django dependency via ImageField) instead.
_ALLOWED_IMAGE_FORMATS = {'PNG', 'JPEG', 'GIF', 'WEBP'}

_HEX_COLOR_RE = re.compile(r'^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$')


def validate_hex_color(value):
    """
    Enforce a strict 3- or 6-digit hex color (e.g. '#2563EB' or '#FFF').
    Without this, primary_color/accent_color (CharField(max_length=7), no
    format constraint) can hold arbitrary 7-character strings such as
    '#f;}</s>' which, even after html.escape() in invoice_pdf(), can break
    out of the inline CSS <style> block these values are interpolated into
    and inject markup into the generated PDF.
    """
    if not _HEX_COLOR_RE.match(value or ''):
        raise ValidationError(
            f'"{value}" nuk është një ngjyrë hex e vlefshme (p.sh. #2563EB).'
        )


def _relative_luminance(hex_color):
    """
    WCAG relative luminance for a 3- or 6-digit hex color. Assumes the value
    has already passed validate_hex_color.
    """
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def linearize(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = linearize(r), linearize(g), linearize(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a, hex_b):
    """WCAG contrast ratio (1:1 to 21:1) between two hex colors."""
    l1 = _relative_luminance(hex_a)
    l2 = _relative_luminance(hex_b)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def validate_color_contrast(background, text, minimum=4.5):
    """
    Reject a background/text color pair that would render illegibly on the
    public storefront. 4.5:1 is the WCAG AA threshold for normal-size body
    text. Unlike primary_color/accent_color (small chrome accents — buttons,
    borders — where a poor choice looks bad but the page stays readable),
    background_color/text_color together determine whether the ENTIRE
    storefront body copy is readable, so this is enforced rather than left
    to tenant taste.

    Deliberately re-validates hex format before computing luminance rather
    than assuming the caller already did: Tenant.clean() (Django's
    full_clean()) runs even when clean_fields() has already rejected one of
    these fields as malformed, so this can be called with a value that
    isn't valid hex. Without this guard, that case raised an unhandled
    ValueError from the hex parsing instead of a normal ValidationError —
    a real 500 in the API instead of a 400, caught by this validator's own
    test suite.
    """
    if not background or not text:
        return
    try:
        validate_hex_color(background)
        validate_hex_color(text)
    except ValidationError:
        # Already-invalid format is validate_hex_color's error to report
        # (on the relevant field, via clean_fields()); contrast is a
        # separate, secondary concern that doesn't apply until format is
        # valid, so silently skip rather than raising a duplicate/confusing
        # error here.
        return
    ratio = contrast_ratio(background, text)
    if ratio < minimum:
        raise ValidationError(
            f'Kontrasti mes ngjyrës së sfondit ({background}) dhe tekstit ({text}) '
            f'është {ratio:.1f}:1 — shumë i ulët për t\'u lexuar. Nevojitet të '
            f'paktën {minimum}:1.'
        )


def validate_image_type(file):
    """
    Reject uploads whose binary content does not match a known-safe image
    format.  Django's ImageField already calls Pillow to verify the header,
    but only raises an error for *completely* unreadable files — it accepts
    polyglot files (e.g. a PHP script with a valid JPEG header appended).
    This validator adds a secondary check via Pillow's Image.open(), which
    reads and verifies the file header without fully decoding pixel data
    (lazy loading), to guard against that.
    """
    if not file:
        return
    try:
        from PIL import Image
        file.seek(0)
        img = Image.open(file)
        # HIGH-3 FIX (v36): Capture format BEFORE verify(). Pillow sets
        # img.format during Image.open() (lazy header read). After verify()
        # is called the image object is invalidated and img.format may be
        # None on some Pillow versions/formats where identification is lazy.
        detected = img.format
        img.verify()          # raises if header is corrupt/unrecognised
        file.seek(0)
    except ValidationError:
        raise
    except Exception:
        raise ValidationError("Nuk mund të lexohet formati i skedarit.")

    if detected is None:
        raise ValidationError("Formati i skedarit nuk u njoh (format i panjohur).")

    if detected not in _ALLOWED_IMAGE_FORMATS:
        raise ValidationError(
            f"Formati '{detected or 'i panjohur'}' nuk lejohet. "
            "Lejohen: PNG, JPEG, GIF, WEBP."
        )
