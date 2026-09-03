"""Photoreal camera-style presets. Natural-language prompts work best on Z-Image."""

# Shared photography language — photoreal, adult, not illustration.
_PHOTO = (
    "photorealistic photograph, shot on a 85mm lens, natural skin texture, "
    "visible pores, realistic lighting, candid, no cartoon, no anime, "
    "no illustration, no CGI, no plastic skin"
)

PRESETS = {
    "golden": {
        "title": "Golden hour",
        "prompt": (
            f"{_PHOTO}. Outdoor golden-hour portrait of the same adult, warm sunlight, "
            "soft rim light, shallow depth of field, casual summer clothes, "
            "city rooftop or park, Kodak portra colors"
        ),
    },
    "studio": {
        "title": "Studio",
        "prompt": (
            f"{_PHOTO}. Clean studio portrait of the same adult, softbox key light, "
            "subtle hair light, seamless grey backdrop, fashion lookbook, "
            "tailored outfit, sharp eyes"
        ),
    },
    "street": {
        "title": "Street night",
        "prompt": (
            f"{_PHOTO}. Night street photograph of the same adult, neon and tungsten "
            "mixed lighting, wet pavement reflections, cinematic, "
            "leather jacket, handheld documentary feel"
        ),
    },
    "hotel": {
        "title": "Hotel window",
        "prompt": (
            f"{_PHOTO}. The same adult in a luxury hotel room at night, city lights "
            "through the window, warm practical lamps, silk slip dress or open shirt, "
            "editorial lifestyle, intimate but classy"
        ),
    },
    "beach": {
        "title": "Beach",
        "prompt": (
            f"{_PHOTO}. The same adult on a beach at late afternoon, salty air, "
            "wind in hair, swimwear, wet skin highlights, hard sun and fill, "
            "film still, ocean bokeh"
        ),
    },
    "pool": {
        "title": "Pool night",
        "prompt": (
            f"{_PHOTO}. The same adult by a hotel pool at night, underwater lights, "
            "turquoise reflections, swimsuit, wet hair, candid, "
            "expensive vacation editorial"
        ),
    },
    "bedroom": {
        "title": "Bedroom",
        "prompt": (
            f"{_PHOTO}. The same adult in a dim bedroom, morning window light, "
            "linen sheets, oversized shirt, sleepy candid, natural, "
            "lifestyle photograph"
        ),
    },
    "rain": {
        "title": "Rain",
        "prompt": (
            f"{_PHOTO}. The same adult in heavy rain at night, soaked clothes, "
            "streetlights, droplets on skin and hair, cinematic still, "
            "moody, high contrast"
        ),
    },
    "gym": {
        "title": "Gym",
        "prompt": (
            f"{_PHOTO}. The same adult in a gym, athletic wear, sweat, "
            "overhead industrial lights, documentary sports photo, "
            "realistic muscle and skin"
        ),
    },
    "custom": {
        "title": "Use my caption",
        "prompt": _PHOTO,
    },
}

STRENGTHS = {
    "keep": {"title": "Keep likeness", "value": 0.40},
    "balanced": {"title": "Balanced", "value": 0.58},
    "restyle": {"title": "Restyle", "value": 0.72},
}

DEFAULT_STRENGTH = "balanced"
MAX_PHOTOS = 10
