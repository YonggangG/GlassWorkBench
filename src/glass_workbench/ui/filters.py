"""Shared global glass filters for calculation and catalog browsers."""


def filtered_glasses(glasses, supplier="Both", preset="All first-sheet glasses", melt="Any melt category", search="", supplements=()):
    output = []
    selected_supplements = set(supplements)
    for glass in glasses:
        if supplier not in ("Both", "All suppliers") and glass.supplier != supplier:
            continue
        if glass.supplemental:
            if glass.uid not in selected_supplements:
                continue
        else:
            if preset == "H- or N-" and not glass.name.startswith(("H-", "N-")):
                continue
            if preset == "Popular: (CDGM H- ∩ MA) or SCHOTT N-":
                if not ((glass.supplier == "CDGM" and glass.name.startswith("H-") and glass.melt_frequency == "MA")
                        or (glass.supplier == "SCHOTT" and glass.name.startswith("N-"))):
                    continue
            if melt != "Any melt category" and glass.melt_frequency != melt:
                continue
        if search and not glass.name.casefold().startswith(search.casefold()):
            continue
        output.append(glass)
    return output
