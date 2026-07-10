"""Hidden curation fixture B — evaluated ONCE, never used for prompt tuning.

Review requirement #3: fixture A ("hard_fixture") was seen repeatedly while
the placement prompt evolved, so even with fixture-disjoint exemplars a
test-set-adaptive-tuning risk remains. Fixture B is authored fresh under
three constraints and then FROZEN:

1. Domain-disjoint from fixture A (no networking/db/dough/training/finance/
   espresso/photography/korean-cooking) AND from the prompt's own exemplars
   (no python/rust, guitar/piano, car/bicycle).
2. Same difficulty mechanics as A: confusable sibling clusters sharing
   vocabulary (telescope vs astrophoto share mount/exposure/lens; freshwater
   vs saltwater aquarium share tank/filter/cycle; bouldering vs rope share
   grip/route/crash), plus distractor singletons that must stay unlinked.
3. The curation prompt and executor are frozen BEFORE the first run; results
   are reported for every completed pass, no reruns, no prompt edits after.

10 clusters (sizes 5-6, 64 notes) -> 110 intra-cluster pairs + 12 distractors.
"""

from __future__ import annotations

import itertools
from pathlib import Path

CLUSTERS: dict[str, list[tuple[str, str]]] = {
    "telescope-observing": [
        ("Collimating the dob", "collimate the primary mirror with a cheshire; a miscollimated dob smears stars at high power."),
        ("Eyepiece focal lengths", "a 25mm eyepiece frames clusters; barlow the 10mm for planets when seeing allows."),
        ("Star hopping", "star-hop from the bright anchor star; a telrad and a wide eyepiece beat go-to for learning the sky."),
        ("Dark adaptation", "thirty minutes of dark adaptation; red light only, and averted vision pulls faint fuzzies out."),
        ("Seeing vs transparency", "steady seeing favors planets at high power; transparency matters more for faint galaxies."),
        ("Dew control", "a dew shield and a low-power heater strap keep the corrector clear on humid nights."),
    ],
    "astrophotography": [
        ("Tracking mount alignment", "polar-align the equatorial mount; drift alignment tightens it before long exposures."),
        ("Stacking subs", "stack ninety 120-second subs with darks and flats; integration beats any single exposure."),
        ("Guiding setup", "an off-axis guider corrects mount error; keep total RMS under one arcsecond for round stars."),
        ("Narrowband filters", "shoot hydrogen-alpha under moonlight; narrowband rescues exposure when the sky glows."),
        ("Histogram exposure", "expose until the histogram peak sits a third from the left; clipping blacks loses nebula."),
        ("Mosaic planning", "plan a two-panel mosaic with 20% overlap; plate-solve each panel before the exposure run."),
    ],
    "freshwater-aquarium": [
        ("Cycling a new tank", "cycle the tank four weeks; ammonia then nitrite must hit zero before fish go in."),
        ("Planted substrate", "aquasoil under sand grows carpets; root tabs feed heavy root feeders like swords."),
        ("Water change rhythm", "weekly 30% water change; dechlorinate and temperature-match before refilling the tank."),
        ("CO2 injection", "one bubble per second CO2 at lights-on; a drop checker green keeps the carpet pearling."),
        ("Community stocking", "stock the community tank slowly; schooling tetras first, the centerpiece fish last."),
    ],
    "saltwater-reef": [
        ("Live rock curing", "cure live rock until ammonia reads zero; die-off in a new reef tank spikes the cycle."),
        ("Protein skimmer tuning", "tune the skimmer to a wet skim during the ugly phase; nutrient export beats dosing."),
        ("Reef salinity", "keep salinity at 1.026 with an ATO; swings stress corals faster than absolute level."),
        ("Coral placement", "place SPS high in the flow under the light; LPS lower where the flow is gentle."),
        ("Alkalinity dosing", "dose alkalinity to hold 8.5 dKH; test twice weekly while the tank matures."),
    ],
    "bouldering": [
        ("Crimp strength cycles", "hangboard half-crimp twice a week; tendons adapt slower than muscles, load gently."),
        ("Reading boulder problems", "read the problem from the ground; find the crux hold and work the sequence backwards."),
        ("Heel hook technique", "a solid heel hook takes weight off the arms; point the toe and pull with the hamstring."),
        ("Crash pad placement", "stack crash pads under the crux move; a spotter guides the fall onto the pad."),
        ("Flash pyramid", "build a flash pyramid: many easy problems under the project grade keep sessions honest."),
    ],
    "rope-climbing": [
        ("Belay device backup", "belay with an assisted-braking device; keep a brake hand on the rope at all times."),
        ("Clipping stances", "clip from a straight-arm stance at the bolt; high-clipping adds fall distance not safety."),
        ("Redpoint tactics", "hang the draws on the redpoint project; rehearse the crux link before the send go."),
        ("Rope management", "flake the rope before every pitch; a middle mark keeps the lower-off honest."),
        ("Falling practice", "practice falls build lead confidence; start below the bolt and lengthen gradually."),
    ],
    "sewing": [
        ("Pattern grading", "grade the pattern between sizes at the side seams; blend the curves smoothly."),
        ("Seam finishing", "french seams enclose raw edges on light fabric; overlock heavier weaves instead."),
        ("Zipper insertion", "baste the invisible zipper first; press the coils flat so the foot rides close."),
        ("Fabric grain", "cut on the straight grain unless the drape needs bias; off-grain hems twist after wash."),
        ("Muslin fitting", "sew a muslin toile first; transfer the fit changes back to the paper pattern."),
    ],
    "beekeeping": [
        ("Hive inspection cadence", "inspect the hive every ten days in spring; look for queen cells and brood pattern."),
        ("Varroa monitoring", "an alcohol wash counts varroa mites; treat past three mites per hundred bees."),
        ("Swarm prevention", "add a super before the brood box crowds; a checkerboarded box delays swarming."),
        ("Winter feeding", "feed 2:1 syrup in autumn until the hive weighs enough; fondant covers midwinter."),
        ("Queen spotting", "find the queen by her long abdomen and steady walk; mark her on a warm calm day."),
    ],
    "fountain-pens": [
        ("Nib tuning", "align the tines under a loupe; a baby's-bottom grind skips on the down stroke."),
        ("Ink flow adjustment", "widen the tine gap a hair for wetter flow; dry writers often need a channel clean."),
        ("Converter cleaning", "flush the converter with bulb syringe water until clear; dried ink starves the feed."),
        ("Paper for fountain pens", "coated paper keeps sheen and stops feathering; cheap copy stock bleeds through."),
        ("Vintage flex nibs", "vintage gold flex spreads to double broad; heavy hands spring modern nibs."),
    ],
    "chess-endgames": [
        ("Lucena position", "build the bridge in the Lucena; the rook lifts to the fourth to shield checks."),
        ("Philidor defense", "hold the Philidor with the rook on the third rank; cut checks after the pawn advances."),
        ("Opposition basics", "take the opposition in king-pawn endings; the defender gives ground on the diagonal."),
        ("Rook behind passed pawn", "rooks belong behind passed pawns, yours or theirs; in front they block promotion."),
        ("Wrong bishop corner", "the wrong-colored bishop cannot win the rook pawn corner; know the draw before trading."),
    ],
}

DISTRACTORS: list[tuple[str, str]] = [
    ("Renew car insurance", "compare quotes before the March renewal."),
    ("Dentist reminder", "six-month cleaning due next week."),
    ("Gift wrap supplies", "buy ribbon and kraft paper for the weekend."),
    ("Warranty receipt", "keep the blender receipt for the two-year warranty."),
    ("Meter reading", "submit the electricity meter reading by the 25th."),
    ("Library card renewal", "renew the library card before it lapses."),
    ("Winter tires", "book the tire swap before the first frost."),
    ("Passport photos", "get new passport photos, old ones expired."),
    ("Neighbor's plant", "water the neighbor's monstera while they travel."),
    ("Software license", "the IDE license renews in November."),
    ("Package pickup", "parcel waiting at the locker until Friday."),
    ("Recycling schedule", "glass pickup alternates Wednesdays."),
]


def total_pairs() -> int:
    return sum(len(list(itertools.combinations(c, 2))) for c in CLUSTERS.values())


def truth_pairs(slug_fn) -> set:
    pairs = set()
    for notes in CLUSTERS.values():
        slugs = [slug_fn(t) for t, _ in notes]
        for a, b in itertools.combinations(slugs, 2):
            pairs.add(frozenset((a, b)))
    return pairs


def seed(vault: Path) -> dict:
    from birkin.mnemosyne import slug
    vault.mkdir(parents=True, exist_ok=True)

    def _note(title: str, body: str) -> str:
        return ("---\n"
                f"title: {title}\n"
                "type: fact\ncreated: 2026-07-08\nupdated: 2026-07-08\n"
                "confidence: 0.7\npolarity: positive\nversion: 1\n"
                "sources: [\"seed\"]\ntags: []\n---\n\n" + body + "\n")

    truth = {"clusters": {}, "distractors": []}
    for zone, notes in CLUSTERS.items():
        truth["clusters"][zone] = []
        for title, body in notes:
            s = slug(title)
            truth["clusters"][zone].append(s)
            (vault / f"{s}.md").write_text(_note(title, body), encoding="utf-8")
    for title, body in DISTRACTORS:
        s = slug(title)
        truth["distractors"].append(s)
        (vault / f"{s}.md").write_text(_note(title, body), encoding="utf-8")
    return truth


if __name__ == "__main__":
    n = sum(len(c) for c in CLUSTERS.values()) + len(DISTRACTORS)
    print(f"clusters={len(CLUSTERS)} notes={n} pairs={total_pairs()} "
          f"distractors={len(DISTRACTORS)}")
