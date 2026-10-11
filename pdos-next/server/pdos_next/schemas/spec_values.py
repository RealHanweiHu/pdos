"""Value shape shared by proposal, native definition and fixed snapshot inputs."""


def numeric_value_shape(value_type, value, lower, upper, text):
    if text is not None:
        return False
    bounds = lower is not None or upper is not None
    if lower is not None and upper is not None and lower > upper:
        return False
    if value_type == "number" and value is not None:
        return not bounds
    return value is None and bounds and value_type in {"number", "range"}
