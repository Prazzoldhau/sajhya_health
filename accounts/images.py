"""Photo handling shared by patient photos (and reusable for other uploads)."""
import io

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PHOTO_BYTES = 8 * 1024 * 1024  # what we accept from the browser
MAX_PHOTO_PIXELS = 640  # what we keep: longest side
Image.MAX_IMAGE_PIXELS = 50_000_000  # refuse decompression bombs


def normalize_photo(upload, base_name='photo', max_bytes=MAX_PHOTO_BYTES, fit=None, max_side=MAX_PHOTO_PIXELS):
    """Validate an uploaded picture and return a small, EXIF-stripped, upright JPEG as a ContentFile.

    Raises ValidationError when the file is not a real image (a renamed .exe, a text file, a huge bomb)."""
    if upload.size > max_bytes:
        raise ValidationError(f'The picture is larger than {max_bytes // (1024 * 1024)} MB.')
    try:
        image = Image.open(upload)
        image.verify()  # cheap structural check
        upload.seek(0)
        image = Image.open(upload)
        image = ImageOps.exif_transpose(image)  # respect phone orientation, then drop all metadata on save
        if image.mode not in ('RGB', 'L'):
            background = Image.new('RGB', image.size, 'white')  # flatten transparency onto white
            background.paste(image.convert('RGBA'), mask=image.convert('RGBA').split()[-1])
            image = background
        else:
            image = image.convert('RGB')
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise ValidationError('Upload a JPEG, PNG or WebP picture.')
    if fit:
        image = ImageOps.fit(image, fit, Image.LANCZOS)  # crop to the exact shape (e.g. 16:9) then resize
    else:
        image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=85, optimize=True)
    return ContentFile(buffer.getvalue(), name=f'{base_name}.jpg')
