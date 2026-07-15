from .models import BUSINESS_TYPE_CHOICES

CATEGORY_LABELS = {
    'retail':        'Tregti',
    'food':          'Ushqim & Mikpritje',
    'rentals':       'Qira',
    'health_beauty': 'Shëndet & Bukuri',
    'services':      'Shërbime',
    'education':     'Arsim',
    'professional':  'Profesionale & B2B',
}

BUSINESS_TYPE_META = {
    'market':           {'icon': '🛒', 'category': 'retail', 'label_sq': 'Market'},
    'pharmacy':         {'icon': '💊', 'category': 'retail', 'label_sq': 'Farmaci'},
    'electronics':      {'icon': '📱', 'category': 'retail', 'label_sq': 'Elektronikë'},
    'clothing':         {'icon': '👗', 'category': 'retail', 'label_sq': 'Veshje'},
    'organic':          {'icon': '🌿', 'category': 'retail', 'label_sq': 'Treg Organik'},
    'bookstore':        {'icon': '📚', 'category': 'retail', 'label_sq': 'Librari & Kancelari'},
    'jewelry':          {'icon': '💍', 'category': 'retail', 'label_sq': 'Bizhuteri & Aksesorë'},
    'toy_store':        {'icon': '🧸', 'category': 'retail', 'label_sq': 'Lodra & Artikuj Bebesh'},
    'sports_shop':      {'icon': '🏀', 'category': 'retail', 'label_sq': 'Artikuj Sportivë'},
    'furniture':        {'icon': '🛋️', 'category': 'retail', 'label_sq': 'Mobilje & Dekor'},
    'petrol_station':   {'icon': '⛽', 'category': 'retail', 'label_sq': 'Stacion Karburanti'},

    'restaurant':       {'icon': '🍽️', 'category': 'food', 'label_sq': 'Restorant / Kafe'},
    'hotel':            {'icon': '🏨', 'category': 'food', 'label_sq': 'Hotel'},
    'bar':               {'icon': '🍸', 'category': 'food', 'label_sq': 'Bar / Klub Nate'},
    'delivery_kitchen': {'icon': '🛵', 'category': 'food', 'label_sq': 'Kuzhinë Delivery'},
    'bakery':           {'icon': '🥐', 'category': 'food', 'label_sq': 'Furrë & Pastiçeri'},
    'catering':         {'icon': '🍱', 'category': 'food', 'label_sq': 'Catering'},

    'car_rental':       {'icon': '🚗', 'category': 'rentals', 'label_sq': 'Makina me Qira'},
    'property_rental':  {'icon': '🏠', 'category': 'rentals', 'label_sq': 'Prona me Qira'},
    'equipment_rental': {'icon': '🛠️', 'category': 'rentals', 'label_sq': 'Pajisje me Qira'},
    'boat_rental':      {'icon': '⛵', 'category': 'rentals', 'label_sq': 'Barka me Qira'},

    'barbershop':       {'icon': '💈', 'category': 'health_beauty', 'label_sq': 'Berber / Salon Flokësh'},
    'spa':              {'icon': '💆', 'category': 'health_beauty', 'label_sq': 'Spa & Wellness'},
    'gym':              {'icon': '🏋️', 'category': 'health_beauty', 'label_sq': 'Palestër'},
    'clinic':           {'icon': '🏥', 'category': 'health_beauty', 'label_sq': 'Klinikë / Dentar'},
    'tattoo':           {'icon': '🎨', 'category': 'health_beauty', 'label_sq': 'Studio Tatuazhesh'},
    'veterinary':       {'icon': '🐾', 'category': 'health_beauty', 'label_sq': 'Klinikë Veterinare'},
    'optician':         {'icon': '👓', 'category': 'health_beauty', 'label_sq': 'Optikë'},

    'auto_repair':      {'icon': '🔧', 'category': 'services', 'label_sq': 'Servis Auto'},
    'cleaning':         {'icon': '🧹', 'category': 'services', 'label_sq': 'Pastrim'},
    'lawyer':           {'icon': '⚖️', 'category': 'services', 'label_sq': 'Avokat / Noter'},
    'accounting':       {'icon': '📊', 'category': 'services', 'label_sq': 'Kontabilitet'},
    'event_agency':     {'icon': '🎭', 'category': 'services', 'label_sq': 'Agjenci Eventesh'},
    'photography':      {'icon': '📷', 'category': 'services', 'label_sq': 'Studio Fotografike'},
    'printing':         {'icon': '🖨️', 'category': 'services', 'label_sq': 'Print & Dizajn'},
    'travel_agency':    {'icon': '🚢', 'category': 'services', 'label_sq': 'Agjenci Udhëtimesh'},
    'funeral_home':     {'icon': '🕊️', 'category': 'services', 'label_sq': 'Shtëpi Funerali'},
    'security':         {'icon': '🛡️', 'category': 'services', 'label_sq': 'Kompani Sigurie'},

    'language_school':  {'icon': '🌍', 'category': 'education', 'label_sq': 'Shkollë Gjuhësh'},
    'tutoring':         {'icon': '📚', 'category': 'education', 'label_sq': 'Qendër Përgatitjeje'},
    'driving_school':   {'icon': '🚙', 'category': 'education', 'label_sq': 'Autoshkollë'},
    'coding_bootcamp':  {'icon': '💻', 'category': 'education', 'label_sq': 'Bootcamp Programimi'},
    'nursery':          {'icon': '🧒', 'category': 'education', 'label_sq': 'Kopsht Fëmijësh'},

    'real_estate':      {'icon': '🏠', 'category': 'professional', 'label_sq': 'Agjenci Imobiliare'},
    'construction':     {'icon': '🏗️', 'category': 'professional', 'label_sq': 'Ndërtim'},
    'architecture':     {'icon': '📐', 'category': 'professional', 'label_sq': 'Arkitekturë & Dizajn'},
    'import_export':    {'icon': '🚛', 'category': 'professional', 'label_sq': 'Import / Eksport'},
    'agro':             {'icon': '🌾', 'category': 'professional', 'label_sq': 'Furnizues Bujqësor'},
    'transport':        {'icon': '🚐', 'category': 'professional', 'label_sq': 'Transport & Logjistikë'},
    'it_company':       {'icon': '🖥️', 'category': 'professional', 'label_sq': 'Kompani IT'},
    'marketing_agency': {'icon': '📈', 'category': 'professional', 'label_sq': 'Agjenci Marketingu'},
}

DEFAULT_ICON = '🏢'


def business_types_payload(counts_by_type=None):
    counts_by_type = counts_by_type or {}
    items = []
    for value, label_en in BUSINESS_TYPE_CHOICES:
        meta = BUSINESS_TYPE_META.get(value, {})
        items.append({
            'value': value,
            'label': meta.get('label_sq', label_en),
            'label_en': label_en,
            'icon': meta.get('icon', DEFAULT_ICON),
            'category': meta.get('category', 'services'),
            'category_label': CATEGORY_LABELS.get(meta.get('category', 'services'), 'Shërbime'),
            'tenant_count': counts_by_type.get(value, 0),
        })
    return items
