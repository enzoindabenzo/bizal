"""
Gap-coverage tests for bizal/validators.py.
"""
import io
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from bizal.validators import (
    contrast_ratio,
    validate_color_contrast,
    validate_hex_color,
    validate_image_type,
)


def make_image_bytes(fmt='PNG', size=(10, 10), color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format=fmt)
    buf.seek(0)
    return buf.read()


class ValidateHexColorTests(SimpleTestCase):
    def test_valid_6_digit_hex(self):
        validate_hex_color('#2563EB')  # should not raise

    def test_valid_3_digit_hex(self):
        validate_hex_color('#FFF')  # should not raise

    def test_invalid_hex_raises(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_hex_color('#f;}</s>')
        self.assertIn('nuk është', str(ctx.exception))

    def test_none_value_raises(self):
        with self.assertRaises(ValidationError):
            validate_hex_color(None)


class ContrastRatioTests(SimpleTestCase):
    def test_3_digit_hex_expansion(self):
        # Exercises the 3-digit -> 6-digit expansion branch in
        # _relative_luminance via contrast_ratio.
        ratio = contrast_ratio('#000', '#FFF')
        self.assertAlmostEqual(ratio, 21.0, places=1)

    def test_6_digit_hex(self):
        ratio = contrast_ratio('#000000', '#FFFFFF')
        self.assertAlmostEqual(ratio, 21.0, places=1)

    def test_identical_colors_ratio_is_one(self):
        ratio = contrast_ratio('#336699', '#336699')
        self.assertAlmostEqual(ratio, 1.0, places=1)


class ValidateColorContrastTests(SimpleTestCase):
    def test_missing_background_returns_silently(self):
        validate_color_contrast('', '#000000')  # no raise

    def test_missing_text_returns_silently(self):
        validate_color_contrast('#FFFFFF', '')  # no raise

    def test_both_missing_returns_silently(self):
        validate_color_contrast('', '')  # no raise

    def test_sufficient_contrast_passes(self):
        validate_color_contrast('#FFFFFF', '#000000')  # no raise

    def test_insufficient_contrast_raises(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_color_contrast('#FFFFFF', '#FEFEFE')
        self.assertIn('Kontrasti', str(ctx.exception))

    def test_invalid_hex_format_skips_silently(self):
        # One value fails validate_hex_color -> caught and returns without
        # raising a second/duplicate error.
        validate_color_contrast('#f;}</s>', '#000000')  # no raise
        validate_color_contrast('#000000', 'not-a-color')  # no raise


class ValidateImageTypeTests(SimpleTestCase):
    def test_falsy_file_returns_silently(self):
        validate_image_type(None)  # no raise

    def test_valid_png_passes(self):
        f = SimpleUploadedFile('a.png', make_image_bytes('PNG'), content_type='image/png')
        validate_image_type(f)  # no raise

    def test_disallowed_format_raises(self):
        f = SimpleUploadedFile('a.bmp', make_image_bytes('BMP'), content_type='image/bmp')
        with self.assertRaises(ValidationError) as ctx:
            validate_image_type(f)
        self.assertIn('nuk lejohet', str(ctx.exception))

    def test_corrupt_file_raises_unreadable_error(self):
        f = SimpleUploadedFile('a.png', b'not-an-image-at-all', content_type='image/png')
        with self.assertRaises(ValidationError) as ctx:
            validate_image_type(f)
        self.assertIn('Nuk mund të lexohet', str(ctx.exception))

    def test_validation_error_inside_try_reraised_unchanged(self):
        # If a ValidationError is somehow raised inside the try block (e.g.
        # Image.open itself raising one), it must propagate unchanged rather
        # than being wrapped by the generic "unreadable file" handler.
        f = SimpleUploadedFile('a.png', make_image_bytes('PNG'), content_type='image/png')
        with patch('PIL.Image.open', side_effect=ValidationError('custom message')):
            with self.assertRaises(ValidationError) as ctx:
                validate_image_type(f)
        self.assertEqual(ctx.exception.messages, ['custom message'])

    def test_none_detected_format_raises(self):
        f = SimpleUploadedFile('a.png', make_image_bytes('PNG'), content_type='image/png')
        fake_img = type('FakeImg', (), {'format': None, 'verify': lambda self: None})()
        with patch('PIL.Image.open', return_value=fake_img):
            with self.assertRaises(ValidationError) as ctx:
                validate_image_type(f)
        self.assertIn('nuk u njoh', str(ctx.exception))
