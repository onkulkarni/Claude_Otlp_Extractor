"""OTLP JSON -> flat event dicts."""


def coerce(value_dict: dict):
    if "stringValue" in value_dict:
        return value_dict["stringValue"]
    if "intValue" in value_dict:
        return int(value_dict["intValue"])
    if "doubleValue" in value_dict:
        return value_dict["doubleValue"]
    if "boolValue" in value_dict:
        return bool(value_dict["boolValue"])
    return None


def attrs_to_dict(attributes: list) -> dict:
    return {a["key"]: coerce(a["value"]) for a in attributes}


def iter_log_records(doc: dict, source_file: str):
    for rl in doc.get("resourceLogs", []):
        resource_attrs = attrs_to_dict(rl.get("resource", {}).get("attributes", []))
        for sl in rl.get("scopeLogs", []):
            for lr in sl.get("logRecords", []):
                attrs = {**resource_attrs, **attrs_to_dict(lr.get("attributes", []))}
                yield {"_source_file": source_file, **attrs}
