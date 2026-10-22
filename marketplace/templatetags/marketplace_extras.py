from urllib.parse import quote

from django import template
from django.conf import settings

register = template.Library()


@register.filter(name='plain_static')
def plain_static(image_path):
    """Build a /static/... URL directly from STATIC_URL, deliberately
    bypassing collectstatic's manifest (staticfiles.json) via
    {% static %}/ManifestStaticFilesStorage.

    On production that manifest is stale relative to what's actually on
    disk for these dynamically-named product images: the hashed
    filenames it points to 404, while the plain (unhashed) filename
    works. physio_api_app._product_image_url and
    patient_app._image_url already use this same workaround for the
    mobile API -- this filter brings the web marketplace/pharmacy
    templates in line with that, since they were still using
    {% static product.image %} and hitting the same stale-manifest 404s.
    """
    if not image_path:
        return ''
    return f'{settings.STATIC_URL}{quote(str(image_path), safe="/")}'


# Cropped from composite reference images the user provided -- one photo per
# category, static/categorized_product/category_icons/. Categories not in
# this dict fall back to their `icon` emoji (or the default) in the template.
#
# 2026-08-13 "logo for sajhya.png": Exercise Equipment, Gels & Lubricants
# 2026-08-14 "part1.png"/"part2.png": replaced Behavioural Therapy, Bioderma,
#   Diapers, Electrical Therapy, Fixderma, Hospital Linens & Accessories,
#   Kleida, Lab Coats, Massage Tools with new versions; added the rest.
#   (Nurse & Staff Uniforms, Patient Gowns, Scrubs, Surgical Wear,
#   Slurrp Farm don't exist in every DB yet -- pending category_icons
#   entries here don't hurt, they're just unused until the category exists.)
# 2026-08-23 "ChatGPT Image Aug 23 07_56_54 AM.png": UM Orthotics + Zuvara
#   categories -- Adult Diapers and Baby Wipes & Tissue are from the pending
#   Zuvara import (see zuvara_catalog_import memory), unused until that SQL
#   is actually run.
CATEGORY_ICON_IMAGES = {
    'Adult Diapers': 'adult-diapers.png',
    'Baby Wipes & Tissue': 'baby-wipes-tissue.png',
    'Behavioural Therapy': 'behavioural-therapy.png',
    'Bioderma': 'bioderma.png',
    'Body Belts & Supports': 'body-belts-supports.png',
    'Cervical Supports': 'cervical-supports.png',
    'Diapers': 'diapers.png',
    'Electrical Therapy': 'electrical-therapy.png',
    'Exercise Equipment': 'exercise-equipment.png',
    'Finger Splints': 'finger-splints.png',
    'Fixderma': 'fixderma.png',
    'Foot & Ankle Support': 'foot-ankle-support.png',
    'Fracture Braces': 'fracture-braces.png',
    'Gels & Lubricants': 'gels-lubricants.png',
    'Hospital Linens & Accessories': 'hospital-linens-accessories.png',
    'Kids Range': 'kids-range.png',
    'Kleida': 'kleida.png',
    'Knee Braces': 'knee-braces.png',
    'Lab Coats': 'lab-coats.png',
    'Massage Tools': 'massage-tools.png',
    'Nurse & Staff Uniforms': 'nurse-staff-uniforms.png',
    'Occupational Therapy': 'occupational-therapy.png',
    'Patient Gowns': 'patient-gowns.png',
    'Resistance & Bands': 'resistance-bands.png',
    'Scrubs': 'scrubs.png',
    'Silicone & Allied Products': 'silicone-allied-products.png',
    'Slurrp Farm': 'slurrp-farm.png',
    'Speech Therapy': 'speech-therapy.png',
    'Surgical': 'surgical.png',
    'Surgical Wear': 'surgical-wear.png',
    'Taping & Wrapping': 'taping-wrapping.png',
    'Thermal Therapy': 'thermal-therapy.png',
    'Traction Kits': 'traction-kits.png',
    'Wrist & Forearm Braces': 'wrist-forearm-braces.png',
}


@register.filter(name='category_icon_image')
def category_icon_image(category_name):
    """Static URL for that category's cropped photo, or '' if none exists
    yet -- template falls back to the emoji icon in that case."""
    filename = CATEGORY_ICON_IMAGES.get(category_name)
    if not filename:
        return ''
    return f'{settings.STATIC_URL}categorized_product/category_icons/{quote(filename)}'


@register.filter(name='npr')
def npr(value):
    """'NPR 1200.00', or 'Price on request' for a zero price (pharmacy items that are quoted individually)."""
    try:
        if value is None or float(value) == 0:
            return 'Price on request'
    except (TypeError, ValueError):
        return ''
    return f'NPR {value}'
