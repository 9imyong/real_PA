"""Whole-utterance controls, independent of a recognizer's punctuation."""
import re
import unicodedata


def utterance_control(text: str) -> str | None:
    # Remove endpoint punctuation only. Substrings and extra words remain
    # ordinary requests, including questions about the stop command itself.
    normalized = text.strip().rstrip('.!?。！？…').rstrip()
    if normalized == '그만':
        return 'interrupt'
    if normalized in {'대화 끝', '종료'}:
        return 'close'
    return None


_LIST_MARKER = re.compile(r'^\s*(?:\d+[.)]|[-*•·])\s+', re.MULTILINE)
_MARKDOWN_LINK = re.compile(r'\[([^\]]*)\]\([^)]*\)')
_URL = re.compile(r'https?://\S+')
_MARKUP = re.compile(r'[*_#`>|]+')
_BARE_NUMBER = re.compile(r'\s*\d{1,2}[.)]\s*')
_KEEP_SYMBOLS = frozenset('°℃℉')
# ZWJ, variation selectors and skin-tone modifiers (category Sk, not So).
_EMOJI_JOINERS = frozenset('\u200d\ufe0e\ufe0f' + ''.join(map(chr, range(0x1F3FB, 0x1F400))))


def spoken_text(text: str) -> str:
    """Deterministic TTS hygiene: what a voice should never read aloud.

    Drops emoji/pictographs, list numbering, markdown and URLs. Persona-free:
    it only shapes audio, the displayed text and dialogue history keep the
    original phrase.
    """
    text = _MARKDOWN_LINK.sub(r'\1', text)
    text = _URL.sub('', text)
    text = _LIST_MARKER.sub('', text)
    text = _MARKUP.sub('', text)
    text = ''.join(ch for ch in text if ch in _KEEP_SYMBOLS or not (
        unicodedata.category(ch) in {'So', 'Cs'} or ch in _EMOJI_JOINERS))
    if _BARE_NUMBER.fullmatch(text):
        return ''  # Phrase splitting at '.' can isolate a list number ("1.").
    return re.sub(r'[ \t]+', ' ', text).strip()
