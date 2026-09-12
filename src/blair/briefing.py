from __future__ import annotations

import re

from .models import AgentResult, Briefing

ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
EXPLICIT_RE = re.compile(r"<blair_brief>\s*(.*?)\s*</blair_brief>", re.IGNORECASE | re.DOTALL)
LINK_RE = re.compile(r"!?\[([^\]]+)]\([^)]*\)")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
URL_RE = re.compile(r"(?i)\b(?:https?|ftp)://[^\s<>)\]}]+|\bwww\.[^\s<>)\]}]+")
WINDOWS_PATH_RE = re.compile(
    r"(?i)(?<![\w])(?:[a-z]:[\\/]|\\\\)[^\r\n]*?"
    r"(?=(?:\s+(?:and|but|then|while|where|which|is|was|were|has|have|see)\b)"
    r"|[.!?;,](?=\s|$)|$)"
)
POSIX_PATH_RE = re.compile(
    r"(?i)(?<![\w])/(?:[^\s/]+/)+[^\r\n]*?"
    r"(?=(?:\s+(?:and|but|then|while|where|which|is|was|were|has|have|see)\b)"
    r"|[.!?;,](?=\s|$)|$)"
)
SECRET_RE = re.compile(
    r"(?ix)"
    r"\b(?:sk|pk|rk)-[a-z0-9_-]{12,}\b"
    r"|\bgh[pousr]_[a-z0-9]{20,}\b"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\beyJ[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\b"
    r"|\b(?:bearer|api[_ -]?key|access[_ -]?token|secret|password)\s*[:=]\s*\S+"
)
LONG_ID_RE = re.compile(r"(?i)\b(?:[0-9a-f]{16,}|[a-z0-9_-]{32,})\b")
DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@(?: .*)?$")
DIFF_METADATA_RE = re.compile(
    r"^(?:index |--- |\+\+\+ |old mode |new mode |deleted file mode |new file mode "
    r"|similarity index |dissimilarity index |rename from |rename to |copy from |copy to "
    r"|Binary files |\\ No newline at end of file$)"
)


def compose_briefing(
    result: AgentResult, *, honorific: str = "sir", max_words: int = 58
) -> Briefing:
    # Preserve indentation so a diff's context marker can be distinguished from its margin.
    raw = ANSI_RE.sub("", result.text or "").strip("\r\n")
    explicit = EXPLICIT_RE.search(raw)
    lines, had_table, had_code = _clean_lines(explicit.group(1) if explicit else raw)
    joined = " ".join(lines)
    if result.metadata.get("failed"):
        status = "blocked"
    elif result.metadata.get("background_pending"):
        status = "partial"
    else:
        status = _classify_status(joined or raw)

    details = _choose_details(lines, status)
    intro = {
        "blocked": "The task needs your attention.",
        "partial": "The work is partly complete.",
        "waiting": "The agent is waiting for your input.",
        "success": "The task is complete.",
        "neutral": "The agent has reported back.",
    }[status]

    parts = [intro]
    parts.extend(details)

    suffix = f", {honorific.strip()}" if honorific.strip() else ""
    if had_table:
        parts.append(f"I compiled a table for you{suffix}. Please check the screen for details.")
    elif had_code:
        parts.append("Please check the screen for the code and full details.")

    text = _deduplicate(" ".join(parts))
    text = _limit_words(text, max_words=max_words, preserve_last=had_table or had_code)
    return Briefing(
        text=text,
        status=status,
        had_table=had_table,
        had_code=had_code,
        source="explicit" if explicit else "deterministic",
    )


def _clean_lines(text: str) -> tuple[list[str], bool, bool]:
    cleaned: list[str] = []
    in_code = False
    had_code = False
    had_table = False
    in_diff = False
    old_remaining = new_remaining = diff_indent = 0
    source_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for index, original in enumerate(source_lines):
        line = original.strip()
        if line.startswith("```") or line.startswith("~~~"):
            in_code = not in_code
            had_code = True
            in_diff = False
            old_remaining = new_remaining = 0
            continue
        if in_code:
            had_code = True
            continue

        # A leading +/- is ambiguous with Markdown. Only consume diff body lines
        # after a unified hunk header, and stop at its declared old/new line counts.
        hunk = DIFF_HUNK_RE.fullmatch(line)
        if hunk:
            old_remaining = int(hunk[1]) if hunk[1] is not None else 1
            new_remaining = int(hunk[2]) if hunk[2] is not None else 1
            diff_indent = len(original) - len(original.lstrip())
            in_diff = had_code = True
            continue
        if in_diff and line == r"\ No newline at end of file":
            continue
        if old_remaining or new_remaining:
            marker = original[diff_indent : diff_indent + 1]
            if marker == "-" and old_remaining:
                old_remaining -= 1
                continue
            if marker == "+" and new_remaining:
                new_remaining -= 1
                continue
            if marker == " " and old_remaining and new_remaining:
                old_remaining -= 1
                new_remaining -= 1
                continue
            old_remaining = new_remaining = 0
            in_diff = False
        paired_file_header = (
            line.startswith("--- ")
            and index + 1 < len(source_lines)
            and source_lines[index + 1].strip().startswith("+++ ")
        )
        if line.startswith("diff --git ") or paired_file_header:
            in_diff = had_code = True
            continue
        if in_diff and DIFF_METADATA_RE.match(line):
            continue
        in_diff = False
        if not line:
            continue
        pipe_count = line.count("|")
        if TABLE_SEPARATOR_RE.match(line) or pipe_count >= 2:
            had_table = True
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^(?:[-*+] |\d+[.)]\s+|>\s*)", "", line)
        line = LINK_RE.sub(r"\1", line)
        line = re.sub(r"`[^`]+`", "the referenced item", line)
        # Preserve token shapes for filtering before Markdown removes underscores.
        # The second pass also catches labels exposed by stripping emphasis.
        line = _redact_for_speech(line)
        line = re.sub(r"[*_~`]", "", line)
        line = _redact_for_speech(line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line or re.fullmatch(r"[-=]{3,}", line):
            continue
        if line.lower() in {"summary", "result", "results", "key points", "details"}:
            continue
        if not re.search(r"[.!?]$", line):
            line += "."
        cleaned.append(line)
    return cleaned, had_table, had_code


def _classify_status(text: str) -> str:
    lower = text.casefold()
    scrubbed = re.sub(
        r"\b(?:no|zero|0)\s+(?:errors?|failures?|failed tests?)\b"
        r"|\bwithout errors?\b|\ball tests pass(?:ed)?\b",
        "",
        lower,
    )
    blocked_patterns = (
        r"\bblocked\b",
        r"\b(?:cannot|could not|unable to)\s+(?:complete|continue|finish|proceed)\b",
        r"\b(?:tests?|build|command)\s+(?:failed|failing)\b",
        r"\bneeds? your (?:input|decision|attention|approval)\b",
        r"\b(?:error|failure):",
    )
    if any(re.search(pattern, scrubbed) for pattern in blocked_patterns):
        return "blocked"
    waiting_patterns = (
        r"\b(?:which|what) (?:option|approach|choice)\b",
        r"\b(?:please )?(?:choose|select|confirm|decide)\b",
        r"\b(?:would|do) you (?:like|want|prefer)\b",
        r"\bwaiting for your (?:input|decision|approval|response)\b",
    )
    if text.rstrip().endswith("?") or any(
        re.search(pattern, lower) for pattern in waiting_patterns
    ):
        return "waiting"
    partial_patterns = (
        r"\bpart(?:ly|ially)\b",
        r"\bremaining\b",
        r"\bnot (?:run|tested|verified|complete|completed|finished|available)\b",
        r"\b(?:tests?|checks?|validation) (?:were |was )?not (?:run|performed|verified)\b",
        r"\b(?:could not|unable to) (?:verify|test|validate)\b",
        r"\bunverified\b",
    )
    if any(re.search(pattern, scrubbed) for pattern in partial_patterns):
        return "partial"
    success_patterns = (
        r"\ball tests pass(?:ed)?\b",
        r"\b(?:completed|implemented|fixed|resolved|created|updated|finished)\b",
        r"\bsuccessfully\b",
        r"\b(?:tests?|build)\s+(?:pass|passed|succeeded)\b",
    )
    return (
        "success" if any(re.search(pattern, lower) for pattern in success_patterns) else "neutral"
    )


def _redact_for_speech(text: str) -> str:
    """Remove high-risk detail that should remain visible only in the terminal."""

    text = SECRET_RE.sub("sensitive information", text)
    text = URL_RE.sub(_replace_url, text)
    text = WINDOWS_PATH_RE.sub("a local file", text)
    text = POSIX_PATH_RE.sub("a local file", text)
    text = LONG_ID_RE.sub("a long identifier", text)
    return text


def _replace_url(match: re.Match[str]) -> str:
    trailing = match.group(0)[-1]
    suffix = trailing if trailing in ".,!?;:" else ""
    return "the linked resource" + suffix


def _choose_details(lines: list[str], status: str) -> list[str]:
    if not lines:
        return ["There is no concise text result to report."]
    sentences: list[str] = []
    for line in lines:
        sentences.extend(piece.strip() for piece in SENTENCE_RE.split(line) if piece.strip())
    candidates: list[tuple[bool, int, int, str]] = []
    for index, sentence in enumerate(sentences):
        lower = sentence.casefold()
        if lower.startswith(("sure.", "certainly.", "here is", "here's")):
            continue
        score = 4 if index == 0 else 0
        if re.search(
            r"\b(?:implemented|fixed|created|updated|changed|added|removed|completed|result)\b",
            lower,
        ):
            score += 5
        if re.search(r"\b(?:test|build|verified|validation|check)\b", lower):
            score += 4
        if re.search(r"\b(?:blocked|failed|error|warning|need|approval)\b", lower):
            score += 6 if status in {"blocked", "waiting"} else 2
        if len(sentence.split()) > 32:
            score -= 3
        needs_attention = _classify_status(sentence) in {"blocked", "partial", "waiting"} or bool(
            re.search(
                r"\bwarning\s*:|\b(?:approval|input|decision)\s+(?:is\s+)?(?:required|needed)\b",
                lower,
            )
        )
        candidates.append((needs_attention, score, index, _normalize_sentence(sentence)))
    # Select only the two details we will speak. Put attention items first so
    # source ordering and the word limit cannot favor routine updates over them.
    chosen = sorted(candidates, key=lambda item: (-item[0], -item[1], item[2]))[:2]
    return [item[3] for item in sorted(chosen, key=lambda item: (-item[0], item[2]))]


def _normalize_sentence(sentence: str) -> str:
    sentence = re.sub(r"\s+", " ", sentence).strip()
    if sentence and sentence[-1] not in ".!?:":
        sentence += "."
    return sentence[:1].upper() + sentence[1:] if sentence else sentence


def _deduplicate(text: str) -> str:
    pieces = SENTENCE_RE.split(text)
    seen: set[str] = set()
    output: list[str] = []
    for piece in pieces:
        key = re.sub(r"\W+", " ", piece.casefold()).strip()
        if key and key not in seen:
            output.append(piece.strip())
            seen.add(key)
    return " ".join(output)


def _limit_words(text: str, *, max_words: int, preserve_last: bool) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    sentences = [item.strip() for item in SENTENCE_RE.split(text) if item.strip()]
    last = sentences[-1] if preserve_last and sentences else ""
    selected: list[str] = []
    budget = max_words - len(last.split()) if last else max_words
    for sentence in sentences[:-1] if last else sentences:
        if len(" ".join([*selected, sentence]).split()) > budget:
            break
        selected.append(sentence)
    if not selected:
        selected = [" ".join(words[: max(1, budget)]).rstrip(".,;:") + "."]
    if last:
        selected.append(last)
    return " ".join(selected)
