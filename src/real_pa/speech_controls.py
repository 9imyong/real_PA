"""Whole-utterance controls, independent of a recognizer's punctuation."""


def utterance_control(text: str) -> str | None:
    # Remove endpoint punctuation only. Substrings and extra words remain
    # ordinary requests, including questions about the stop command itself.
    normalized = text.strip().rstrip('.!?。！？…').rstrip()
    if normalized == '그만':
        return 'interrupt'
    if normalized in {'대화 끝', '종료'}:
        return 'close'
    return None
