"""Small shared helpers. No Qt, global mutable search state, or catalog expansion."""
from collections import Counter
from dataclasses import asdict
from itertools import islice
import math

import numpy as np


def batches(iterator, size):
    while chunk := list(islice(iterator, size)):
        yield chunk


def unique_glasses(glasses):
    """UIDs identify catalog rows; do not silently choose conflicting duplicates."""
    unique = {}
    duplicates = 0
    for glass in glasses:
        if glass.uid in unique:
            if glass != unique[glass.uid]:
                raise ValueError(f"Conflicting catalog records for {glass.uid}")
            duplicates += 1
        else:
            unique[glass.uid] = glass
    return sorted(unique.values(), key=lambda g: g.uid), duplicates


def keep_best(existing, new, limit):
    return sorted(existing + new, key=lambda r: (r["score"], r["glass_ids"], r["powers"]))[:limit]


def finite_positive(name, value, zero=False):
    if not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")


def positive_integer(name, value, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < (0 if zero else 1):
        raise ValueError(f"{name} must be an integer >= {0 if zero else 1}")


def base_metadata(glasses, settings, duplicate_inputs):
    return {
        "settings": asdict(settings),
        "input_glass_count": len(glasses) + duplicate_inputs,
        "unique_glass_count": len(glasses),
        "duplicate_input_count": duplicate_inputs,
        "eligible_glass_count": 0,
        "rejected_glass_count": 0,
        "candidate_count": 0,
        "evaluated_count": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "returned_count": 0,
        "glass_rejection_reasons": Counter(),
        "candidate_rejection_reasons": Counter(),
        "sources": [dict(zip(("supplier", "file", "sheet", "sha256"), key)) for key in sorted({
            (g.supplier, g.source_file, g.source_sheet, g.source_hash) for g in glasses
        })],
        "counts_definition": "candidate/evaluated/accepted/rejected count glass tuples; eligible_glass_count counts input glasses; accepted includes rows outside top_k",
    }


def finish_metadata(meta, rows):
    meta["returned_count"] = len(rows)
    meta["unevaluated_count"] = meta["candidate_count"] - meta["evaluated_count"]
    meta["eligible_count"] = meta["eligible_glass_count"]
    for key in ("glass_rejection_reasons", "candidate_rejection_reasons"):
        meta[key] = dict(meta[key])
    return meta
