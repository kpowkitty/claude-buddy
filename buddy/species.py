"""Buddy species roster. 11 species across 5 rarity tiers.

Rarity weights (gacha-standard): common 60, uncommon 25, rare 10, epic 4, legendary 1.
Within a tier, each species is equally likely.

Skills: every buddy has the same 8 skills, scored 0-100. Each species has:
  - a baseline range (e.g. 20-40) for most skills
  - a `signature` skill that rolls from a higher range (e.g. 60-80)
Rarity shifts both ranges up by a bonus (0 / +5 / +10 / +20 / +30).

Each species also has a small 3-line ASCII art for the reveal/card.
"""

RARITY_WEIGHTS = {
    "common": 60,
    "uncommon": 25,
    "rare": 10,
    "epic": 4,
    "legendary": 1,
}

RARITY_ORDER = ["common", "uncommon", "rare", "epic", "legendary"]

RARITY_BONUS = {
    "common": 0,
    "uncommon": 5,
    "rare": 10,
    "epic": 20,
    "legendary": 30,
}

SKILLS = [
    "wisdom",
    "debugging",
    "refactoring",
    "testing",
    "documentation",
    "speed",
    "creativity",
    "patience",
]

SPECIES = {
    "common": [
        {
            "id": "slime",
            "name": "Slime",
            "flavor": "A gelatinous companion. Low-maintenance, high vibes.",
            "signature": "patience",
            "base_range": (15, 35),
            "sig_range": (55, 75),
            "art": [
                r"     .-~~~-.     ",
                r"   .'   o   '.   ",
                r"  (    \_/    )  ",
                r"   '._     _.'   ",
                r"   /~~~~~~~~~\   ",
            ],
        },
        {
            "id": "pebble",
            "name": "Pebble",
            "flavor": "A small rock that blinks sometimes. Loyal.",
            "signature": "patience",
            "base_range": (10, 30),
            "sig_range": (70, 90),
            "art": [
                r"       __        ",
                r"    _-'  '-_     ",
                r"   /  o  o  \    ",
                r"  |    __    |   ",
                r"  \__________/  ",
            ],
        },
        {
            "id": "sprout",
            "name": "Sprout",
            "flavor": "A leaflet with ambition. Photosynthesizes your code.",
            "signature": "creativity",
            "base_range": (20, 40),
            "sig_range": (55, 75),
            "art": [
                r"      \  |  /      ",
                r"       \ | /       ",
                r"        \|/        ",
                r"      ( o.o )     ",
                r"       \===/      ",
                r"        |||       ",
            ],
        },
    ],
    "uncommon": [
        {
            "id": "moth",
            "name": "Moth",
            "flavor": "Drawn to glowing screens. You are its sun.",
            "signature": "documentation",
            "base_range": (20, 40),
            "sig_range": (60, 80),
            "art": [
                r"    __     __     ",
                r"   /  \_o_/  \    ",
                r"   \   ^.^   /    ",
                r"    \_     _/     ",
                r"      \___/       ",
            ],
        },
        {
            "id": "pollywog",
            "name": "Pollywog",
            "flavor": "Half tadpole, half opinion. Will evolve.",
            "signature": "refactoring",
            "base_range": (25, 45),
            "sig_range": (60, 80),
            "art": [
                r"     .---.          ",
                r"   .'     '.        ",
                r"  (  o   o  )~~     ",
                r"   '.  ~  .'~~~     ",
                r"     '---'          ",
            ],
        },
        {
            "id": "ember",
            "name": "Ember",
            "flavor": "A flickering flame with a face. Warm to the touch.",
            "signature": "speed",
            "base_range": (25, 45),
            "sig_range": (65, 85),
            "art": [
                r"       ))        ",
                r"      (( )       ",
                r"       )(        ",
                r"      / ^ \      ",
                r"     ( ^.^ )     ",
                r"      \___/      ",
            ],
        },
    ],
    "rare": [
        {
            "id": "owlet",
            "name": "Owlet",
            "flavor": "Tiny owl. Stays up later than you do.",
            "signature": "wisdom",
            "base_range": (30, 50),
            "sig_range": (70, 90),
            "art": [
                r"      ,___,        ",
                r"     /     \       ",
                r"    | O , O |      ",
                r"    |  /v\  |      ",
                r"     \_____/       ",
                r"     //   \\       ",
            ],
        },
        {
            "id": "cephalo",
            "name": "Cephalo",
            "flavor": "A pocket-sized octopus. Eight opinions, one heart.",
            "signature": "wisdom",
            "base_range": (20, 40),
            "sig_range": (60, 80),
            "art": [
                r"      _____        ",
                r"    .'     '.      ",
                r"   ( o     o )     ",
                r"    '.  ~  .'      ",
                r"    /|/|\|\|\      ",
                r"   ( ( ( ) ) )     ",
            ],
        },
    ],
    "epic": [
        {
            "id": "dragonling",
            "name": "Dragonling",
            "flavor": "Hoards semicolons. Hatched with teeth.",
            "signature": "debugging",
            "base_range": (35, 55),
            "sig_range": (75, 95),
            "art": [
                r"    /\ /\      ",
                r"   ( o o )     ",
                r"   / >{}< \~~~ ",
                r"  |  \VV/  |~~ ",
                r"   \_| |_/     ",
                r"    ^^ ^^      ",
            ],
        },
        {
            "id": "kitsune",
            "name": "Kitsune",
            "flavor": "A fox with one tail for now. More later, maybe.",
            "signature": "testing",
            "base_range": (35, 55),
            "sig_range": (75, 95),
            "art": [
                r"     /\   /\       ",
                r"    (  \_/  )      ",
                r"     \ ^.^ /       ",
                r"      > v <  ~~~~  ",
                r"     /     \ ~~~~~ ",
                r"    (_______)      ",
            ],
        },
    ],
    "legendary": [
        {
            "id": "moonwyrm",
            "name": "Moonwyrm",
            "flavor": "A celestial serpent. You pulled this. The odds were 1 in 100.",
            "signature": "wisdom",
            "base_range": (50, 70),
            "sig_range": (90, 100),
            "art": [
                r"   *  .  *  .  *   ",
                r"     __/~~\__      ",
                r"   _(  O  O  )_    ",
                r"  ( ~  .vv.  ~ )   ",
                r"   '~~~~~~~~~~'    ",
                r"    *  .  *  .     ",
            ],
        },
    ],
}


def all_species_flat():
    out = []
    for rarity in RARITY_ORDER:
        for s in SPECIES[rarity]:
            out.append((rarity, s))
    return out


def find_species(species_id: str):
    for rarity, s in all_species_flat():
        if s["id"] == species_id:
            return rarity, s
    return None, None


def roll_skills(rng, species: dict, rarity: str) -> dict:
    """Return a dict of {skill_name: int} for all SKILLS.

    Each non-signature skill rolls in base_range + rarity_bonus.
    The signature skill rolls in sig_range + rarity_bonus.
    Values are clamped to [0, 100].
    """
    bonus = RARITY_BONUS[rarity]
    base_lo, base_hi = species["base_range"]
    sig_lo, sig_hi = species["sig_range"]
    sig = species["signature"]
    out = {}
    for skill in SKILLS:
        if skill == sig:
            lo, hi = sig_lo + bonus, sig_hi + bonus
        else:
            lo, hi = base_lo + bonus, base_hi + bonus
        out[skill] = max(0, min(100, rng.randint(lo, hi)))
    return out
