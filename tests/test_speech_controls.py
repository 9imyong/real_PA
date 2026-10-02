import unittest

from real_pa.speech_controls import utterance_control


class SpeechControlTests(unittest.TestCase):
    def test_endpoint_punctuation_and_whitespace(self):
        for text in ('그만', ' 그만. ', '그만！', '그만...', '그만?', '그만。'):
            with self.subTest(text=text):
                self.assertEqual(utterance_control(text), 'interrupt')
        for text in ('대화 끝.', ' 종료! ', '대화 끝…'):
            with self.subTest(text=text):
                self.assertEqual(utterance_control(text), 'close')

    def test_commands_must_be_the_entire_utterance(self):
        for text in ('그만이라는 말 뜻은?', '이제 그만해', '그만. 다음 질문',
                     '종료 방법 알려줘.', '대화 끝내는 방법', '', '.', '그만,'):
            with self.subTest(text=text):
                self.assertIsNone(utterance_control(text))


class SpokenTextTests(unittest.TestCase):
    def test_voice_never_reads_lists_markup_links_or_emoji(self):
        from real_pa.speech_controls import spoken_text
        cases = {
            '1.': '',
            '- **밤편지** https://youtu.be/x': '밤편지',
            '[아이유 공식](https://youtube.com) 영상이에요 🐱': '아이유 공식 영상이에요',
            '👍🏻 👨‍👩‍👧 좋아요 ❤️': '좋아요',
            '🥰': '',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(spoken_text(text), expected)

    def test_meaningful_symbols_and_numbers_are_kept(self):
        from real_pa.speech_controls import spoken_text
        for text in ['기온은 13.0°C입니다.', '최고 20℃', '2.5% 올랐어요', '2026.', '1위는 아이유예요.']:
            with self.subTest(text=text):
                self.assertEqual(spoken_text(text), text)
