"""Pull the corridor's hospitals and clinics out of the OSM extract and
snap each one to a network edge.

Sits beside `extract_tier0_config.py` and follows its convention exactly:
a scenario-preparation script that turns the raw OSM artefact into
something the control code can consume, run once and committed as data
rather than re-parsed at simulation time. Junction geometry came out of
the net that way; destinations come out of the OSM that way.

**What is real here and what is inferred**, stated up front because the
distinction matters more for this file than for anything else in the
project.

*Real*: the facility exists, its coordinates are OSM's, its name is
OSM's, and the edge it snaps to is computed from the actual network
geometry. An ambulance routed to that edge arrives at that building.

*Inferred*: the capability tags. OSM records `amenity=hospital` and
sometimes `healthcare:speciality`, but for most of these the only signal
is the name -- "Maxivision Eye Hospital", "American Oncology Institute",
"Ashraf Maternity ENT & Multi Speciality". Reading a capability out of a
name is a keyword match, not a clinical fact. A building called "Multi
Speciality Hospital" may or may not have a cath lab at 3 a.m., and the
name says nothing about whether a bed is free.

So capabilities here are **a plausible model of facility specialisation,
not a clinical directory**, and the code says so wherever it is used. For
a simulation that is the right level of fidelity: it makes
"nearest facility that can treat this" a real routing constraint to
optimise against, without pretending the underlying data supports a
treatment decision. A deployment would replace this file wholesale with
the health authority's own facility register, which is why the output is
a plain JSON document with a stable schema rather than something computed
inline.

Usage:
    python scenarios/networks/vijayawada/extract_facilities.py
writes `facilities.json` next to the network.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("SUMO_HOME", "/usr/share/sumo")
import sumolib  # noqa: E402

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent.parent
NET_PATH = _HERE / "vijayawada_corridor.net.xml"
OSM_PATH = _ROOT / "vijayawada_corridor_bbox.osm.xml"
OUT_PATH = _HERE / "facilities.json"

MERGE_RADIUS_M = 250.0
"""How far apart two OSM records of the same name may sit and still be
one facility. Comfortably larger than the 90-95 m separations this
extract actually contains -- a node placed at the entrance and a building
way centroid are easily that far apart on a hospital campus -- and far
smaller than the distance between two genuinely different facilities that
happen to share a name."""

SNAP_RADIUS_M = 400.0
"""How far a facility may sit from the nearest drivable edge and still be
considered reachable. Generous, because OSM places a hospital node
anywhere inside its grounds -- often the main building, sometimes the
centroid of a large campus -- and the ambulance bay is on the road."""

# Keyword -> capability. Deliberately conservative: a keyword must be
# specific enough that its presence in a facility's name is strong
# evidence, so "care" and "health" are absent and "cardiac" is not.
_CAPABILITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cardiac": ("heart", "cardio", "cardiac"),
    "neuro": ("brain", "neuro", "stroke"),
    "trauma": ("trauma", "accident", "emergency", "casualty"),
    "orthopaedic": ("ortho", "bone", "joint", "spine", "arthrit", "rheumat"),
    "obstetric": ("maternity", "women", "obstetric", "gynec", "nursing home"),
    "paediatric": ("child", "paediatric", "pediatric", "shishu"),
    "oncology": ("oncology", "cancer", "tumour", "tumor"),
    "ophthalmic": ("eye", "vision", "ophthal", "retina"),
    "ent": ("ent ", " ent", "otolaryng"),
    "dental": ("dental", "dentist", "orthodont"),
    "renal": ("kidney", "renal", "nephro", "dialysis"),
    "pulmonary": ("chest", "pulmon", "respirat", "lung"),
}

_SYNONYMS: dict[str, str] = {
    # OSM's `healthcare:speciality` uses its own vocabulary, which
    # overlaps this file's capability names without matching them. Left
    # unnormalised the first run produced `ophthalmic` (12, from names)
    # *and* `ophthalmology` (1, from a tag) as separate capabilities --
    # so a request for one would silently skip a facility that has the
    # other. Two spellings of one capability is a lookup that fails
    # quietly, which is the worst way for a routing constraint to fail.
    "ophthalmology": "ophthalmic",
    "orthopaedics": "orthopaedic",
    "orthopedics": "orthopaedic",
    "paediatrics": "paediatric",
    "pediatrics": "paediatric",
    "children": "paediatric",
    "child": "paediatric",
    "cardiology": "cardiac",
    "neurology": "neuro",
    "neurosurgery": "neuro",
    "gynaecology": "obstetric",
    "gynecology": "obstetric",
    "obstetrics": "obstetric",
    "fertility": "obstetric",
    "nephrology": "renal",
    "dialysis": "renal",
    "pulmonology": "pulmonary",
    "otolaryngology": "ent",
    "dentistry": "dental",
    "emergency": "trauma",
}
"""Declared-tag vocabulary folded onto this file's capability names.

Anything not listed is kept verbatim rather than dropped: an unknown
speciality is information, and discarding it would be worse than
carrying a name nothing currently asks for."""


_GENERAL_KEYWORDS = ("multi speciality", "multispeciality", "multi-speciality",
                     "general", "government", "govt", "medical college", "super")
"""Names that assert breadth rather than a speciality. These get the
`general` capability, which is what an undifferentiated emergency needs."""

_NOT_GENERAL_KEYWORDS = (
    "diagnostic", "laborator", " lab", "scan", "imaging", "radiolog",
    "patholog", "polyclinic", "physio", "ayurved", "homeo", "unani",
    "fertility", "ferti ", "ivf", "blood bank", "pharmac", "optical",
    "veterinar", "skin", "cosmet", "wellness", "rehab",
)
"""Names that rule `general` *out* however the facility is tagged.

OSM's `amenity=hospital` is used loosely -- this extract applies it to
diagnostics centres, fertility clinics and rheumatology practices. The
first version's fallback ("an unlabelled hospital is general") therefore
offered "Tenet Diagnostics" and "Ferti CARE" as destinations for an
undifferentiated emergency, which the live dispatch probe surfaced
immediately: a fertility clinic came back as the nearest general
facility.

A negative list is the right shape for this rather than a stricter
positive one. Requiring positive evidence of breadth would drop the
genuinely unnamed district hospitals that *are* the right destination
and are simply mapped as "X Hospital"; ruling out the facilities whose
names say what they are instead keeps those and removes the labs."""


def _capabilities(name: str, tags: dict[str, str]) -> list[str]:
    """Capability set for one facility.

    OSM's own `healthcare:speciality` tag is preferred wherever it
    exists, because it is asserted by a mapper rather than guessed from a
    string. The keyword pass only fills the gap, which on this extract is
    most of them."""
    caps: set[str] = set()

    declared = tags.get("healthcare:speciality", "")
    for token in declared.replace(",", ";").split(";"):
        token = token.strip().lower()
        if token:
            caps.add(_SYNONYMS.get(token, token))

    lowered = f" {name.lower()} "
    for capability, keywords in _CAPABILITY_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            caps.add(capability)
    excluded_from_general = any(k in lowered for k in _NOT_GENERAL_KEYWORDS)
    if any(k in lowered for k in _GENERAL_KEYWORDS) and not excluded_from_general:
        caps.add("general")

    # NOTE on the residual error rate, which is real and not worth
    # keyword-patching away. A facility whose speciality has no keyword
    # here falls through to `general` -- "Anvitha Arthritis &
    # Rheumatology Centre" did, until "arthrit" was added above. Every
    # such fix narrows the gap for this extract and generalises to no
    # other, so the list is kept at the specialities that actually
    # appear rather than grown toward a taxonomy. The honest statement
    # is that `general` here means "no recognised speciality and not
    # obviously a lab", which is a useful proxy and not a clinical
    # claim; a deployment replaces the whole file with a real register.
    #
    # A hospital with nothing else identifiable is treated as general;
    # a *clinic* is not. That asymmetry is the one clinically-shaped
    # judgement in this file and it errs the safe way: sending an
    # undifferentiated emergency to an unlabelled hospital is defensible,
    # sending one to an unlabelled clinic is not.
    if not caps and tags.get("amenity") == "hospital" and not excluded_from_general:
        caps.add("general")
    return sorted(caps)


def _identity(name: str) -> str:
    """A facility's name reduced to a matching key.

    OSM commonly carries one building as both a node and a way, and the
    two copies rarely agree: this extract has "Anvitha Arthritis &
    Rheumatology Centre" as a clinic and "Anvitha Arthritis and
    Rheumatology Centre" as a hospital, a few metres apart. The first
    version de-duplicated on coordinates rounded to a metre, which those
    two survive -- so the facility appeared twice, under two `amenity`
    values, with two different capability sets. Worse than a double
    count: the duplicate pair *disagreed*, and the copy tagged `hospital`
    picked up the unlabelled-hospital fallback, which is how a fertility
    clinic became a general-emergency destination.

    Normalising "&" to "and" and dropping punctuation and the generic
    tail words makes the two copies match so they can be merged."""
    text = name.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\b(hospital|hospitals|clinic|centre|center|nursing home)\b", " ", text)
    return " ".join(text.split())


def _node_coords(root: ET.Element) -> dict[str, tuple[float, float]]:
    return {
        n.get("id"): (float(n.get("lat")), float(n.get("lon")))
        for n in root.findall("node")
    }


def extract(net_path: Path = NET_PATH, osm_path: Path = OSM_PATH) -> list[dict]:
    net = sumolib.net.readNet(str(net_path))
    root = ET.parse(osm_path).getroot()
    coords = _node_coords(root)

    merged: list[dict] = []
    for element in list(root.findall("node")) + list(root.findall("way")):
        tags = {t.get("k"): t.get("v") for t in element.findall("tag")}
        if tags.get("amenity") not in ("hospital", "clinic"):
            continue

        if element.tag == "node":
            latlon = coords.get(element.get("id"))
        else:
            latlon = next(
                (coords[nd.get("ref")] for nd in element.findall("nd")
                 if nd.get("ref") in coords),
                None,
            )
        if latlon is None:
            continue
        lat, lon = latlon

        x, y = net.convertLonLat2XY(lon, lat)
        candidates = net.getNeighboringEdges(x, y, r=SNAP_RADIUS_M)
        drivable = [
            (edge, dist) for edge, dist in candidates
            if edge.allows("emergency") and not edge.isSpecial()
        ]
        if not drivable:
            continue
        edge, distance = min(drivable, key=lambda pair: pair[1])
        name = tags.get("name", "").strip() or "(unnamed)"

        entry = {
            "id": f"{tags['amenity']}:{element.get('id')}",
            "name": name,
            "kind": tags["amenity"],
            "lat": lat,
            "lon": lon,
            "edge": edge.getID(),
            "edge_offset_m": round(edge.getLength() / 2.0, 1),
            "snap_distance_m": round(distance, 1),
            "capabilities": _capabilities(name, tags),
        }
        # Matched on normalised name *and* actual separation, not on a
        # grid cell. The first attempt keyed on a 100 m cell and merged
        # nothing: the duplicate pairs in this extract sit 90-95 m apart,
        # and two points 90 m apart land in different 100 m cells about
        # as often as not. A cell whose size merely exceeds the distance
        # does not co-locate anything -- only the distance itself does.
        entry["_identity"] = _identity(name)
        entry["_xy"] = (x, y)
        existing = next(
            (
                other
                for other in merged
                if other["_identity"] == entry["_identity"]
                and math.dist(other["_xy"], (x, y)) <= MERGE_RADIUS_M
            ),
            None,
        )
        if existing is None:
            merged.append(entry)
            continue
        # Merge rather than discard: each copy may carry capabilities the
        # other lacks. Keep the snap closest to the road, and let
        # `clinic` win the kind -- the narrower claim is the safer one to
        # keep when two records of the same building disagree.
        existing["capabilities"] = sorted(
            set(existing["capabilities"]) | set(entry["capabilities"])
        )
        if entry["snap_distance_m"] < existing["snap_distance_m"]:
            existing["edge"] = entry["edge"]
            existing["edge_offset_m"] = entry["edge_offset_m"]
            existing["snap_distance_m"] = entry["snap_distance_m"]
        if "clinic" in (existing["kind"], entry["kind"]):
            existing["kind"] = "clinic"

    for entry in merged:
        entry.pop("_identity", None)
        entry.pop("_xy", None)
    return sorted(merged, key=lambda f: f["name"])


def main() -> None:
    facilities = extract()
    OUT_PATH.write_text(json.dumps({"facilities": facilities}, indent=2))

    from collections import Counter

    caps = Counter(c for f in facilities for c in f["capabilities"])
    print(f"{len(facilities)} facilities -> {OUT_PATH.name}")
    print(f"  hospitals {sum(1 for f in facilities if f['kind'] == 'hospital')}, "
          f"clinics {sum(1 for f in facilities if f['kind'] == 'clinic')}")
    print("  capabilities (name-derived unless OSM declared one):")
    for capability, count in caps.most_common():
        print(f"    {capability:14s} {count:3d}")
    unlabelled = [f for f in facilities if not f["capabilities"]]
    if unlabelled:
        print(f"  {len(unlabelled)} with no capability at all "
              "(unlabelled clinics -- not eligible destinations)")


if __name__ == "__main__":
    sys.exit(main())
