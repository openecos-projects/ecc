"""Explicit Sizer process settings, independent of library naming guesses."""


def vt_environment(pdk) -> str:
    groups = pdk.description.get("tools", {}).get("sizer", {}).get("vt_groups", [])
    if not groups:
        return "-num_vt 1\n"
    # The current native ABI has three ordered slots. Package authors supply
    # groups from slow/high-threshold to fast/low-threshold, with arbitrary IDs.
    if len(groups) > 3:
        raise ValueError("Sizer backend supports at most three ordered VT groups")
    ids = [group["id"] for group in groups]
    suffixes = [group.get("suffix", "") for group in groups]
    if len(ids) != len(set(ids)) or len(suffixes) != len(set(suffixes)):
        raise ValueError("duplicate Sizer VT group or suffix")
    lines = [f"-num_vt {len(groups)}"]
    for slot, suffix in zip(("hvt", "nvt", "lvt"), suffixes, strict=False):
        if not suffix or any(character.isspace() for character in suffix):
            raise ValueError("Sizer VT suffix must be a nonempty token")
        lines.append(f"-suffix_{slot} {suffix}")
    return "\n".join(lines) + "\n"
