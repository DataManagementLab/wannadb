"""Shared confirmed, provisional and missing document-mapping progress."""

SUGGESTED_MAPPINGS = "SuggestedAttributeMappingsSignal"


def provisional_attributes(signals):
    value = signals.get(SUGGESTED_MAPPINGS, ())
    return getattr(value, "value", value)


def attribute_progress(documents, names):
    result = []
    for name in names:
        mapped = [document for document in documents if name in document["attribute_mappings"]]
        provisional = sum(name in provisional_attributes(document.get("signals", {}))
                          for document in mapped)
        confirmed = len(mapped) - provisional
        result.append({
            "name": name, "signals": {},
            "populated": bool(documents) and confirmed == len(documents),
            "partial": 0 < confirmed < len(documents),
            "confirmedCount": confirmed, "provisionalCount": provisional,
            "missingCount": len(documents) - len(mapped),
            "nrOfNuggets": sum(len(document["attribute_mappings"][name]) for document in mapped),
        })
    return result
