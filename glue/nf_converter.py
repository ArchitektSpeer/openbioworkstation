"""Conservative conversion of simple nf-core script strings, never Groovy evaluation."""

import re


def convert_script(source, inputs, outputs):
    match = re.search(r'\bscript\s*:(.*?)(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')', source, re.S)
    if not match:
        return ""
    prelude = match[1]
    # Only common task extension defaults are recognized outside the script.
    for line in prelude.splitlines():
        line = line.strip()
        if (
            line
            and not line.startswith("//")
            and not re.fullmatch(
                r"(?:def\s+)?(?:args|prefix)\s*=\s*task\.ext\.(?:args|prefix)\s*\?:\s*.*", line
            )
        ):
            return ""
    script = (match[2] if match[2] is not None else match[3]).strip()
    if any(
        token in script
        for token in ("${if", ".collect", ".join(", "meta.", "task.ext.", "?:", "->")
    ):
        return ""
    # Resolve output globs before generic substitutions, ensuring files match the compiled paths.
    for port in outputs:
        pattern = port.pattern
        if (
            pattern
            and ("${prefix}" in pattern or "$prefix" in pattern)
            and not any(char in pattern for char in "*?[]")
        ):
            script = script.replace(pattern, "{output." + port.name + ":q}")
    replacements = {"task.cpus": "{threads}", "args": "{params.extra}"}
    replacements.update({p.name: "{input." + p.name + ":q}" for p in inputs})
    # Preserve inserted Snakemake fields while rejecting unknown Nextflow substitutions.
    unknown = False

    def substitute(match):
        nonlocal unknown
        name = match[1] or match[2]
        if name not in replacements:
            unknown = True
            return match[0]
        return replacements[name]

    script = re.sub(r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_.]*)", substitute, script)
    if unknown or "$(" in script or "`" in script:
        return ""
    fields = re.findall(r"\{([^{}]+)\}", script)
    accepted = set(replacements.values()) | {"{output." + p.name + ":q}" for p in outputs}
    if any("{" + field + "}" not in accepted for field in fields):
        return ""
    if script.count("{") != len(fields) or script.count("}") != len(fields):
        return ""
    return script
