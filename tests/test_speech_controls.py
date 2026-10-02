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
