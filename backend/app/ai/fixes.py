"""Fix Recommendation Engine: clean up the model's kubectl commands and flag risky ones.

The model writes the fix itself. This step makes sure the commands are
copy-pasteable and warns the user before anything destructive.
"""

import re

from app.models.diagnosis import IssueDiagnosis

# Commands that remove or disrupt things. They are kept, but the user is warned.
RISKY_PATTERNS = [
    (re.compile(r"\bkubectl\s+delete\s+(ns|namespace|namespaces)\b"), "deletes a whole namespace and everything in it"),
    (re.compile(r"\bkubectl\s+delete\b"), "deletes a resource"),
    (re.compile(r"\bkubectl\s+drain\b"), "evicts every pod from a node"),
    (re.compile(r"--force\b"), "uses --force"),
    (re.compile(r"--grace-period[= ]0\b"), "skips graceful shutdown"),
    (re.compile(r"\bkubectl\s+scale\b.*--replicas[= ]0\b"), "scales a workload to zero"),
    (re.compile(r"\bkubectl\s+replace\b"), "replaces the whole resource"),
]


def _clean(command: str) -> str:
    command = command.strip().strip("`").strip()
    command = re.sub(r"^\$\s*", "", command)  # drop a leading shell prompt
    return command


def refine_fix(issue: IssueDiagnosis) -> IssueDiagnosis:
    commands: list[str] = []
    warnings: list[str] = list(issue.warnings)

    for raw in issue.kubectl_commands:
        command = _clean(raw)
        if not command.startswith("kubectl ") or command in commands:
            continue  # keep only real, unique kubectl commands
        commands.append(command)
        for pattern, risk in RISKY_PATTERNS:
            if pattern.search(command):
                warnings.append(f"`{command}` {risk}. Double-check before running it.")
                break

    return issue.model_copy(update={"kubectl_commands": commands, "warnings": warnings})
