from unittest import TestCase

from electrum.i18n import convert_to_iso_639_1, languages


class TestISO639(TestCase):
    def test_lowercase(self):
        self.assertEqual(
            convert_to_iso_639_1('EN'),
            'en'
        )
        self.assertEqual(
            convert_to_iso_639_1('Es'),
            'es'
        )

    def _test_error_raising(self, value):
        with self.assertRaises(ValueError) as e:
            convert_to_iso_639_1(value)
        self.assertIn(str(value), str(e.exception))

    def test_less_than_2_letters(self):
        for value in ('', 'X', 'y'):
            with self.subTest(value):
                self._test_error_raising(value)

    def test_2_first_letter_extraction(self):
        data = {
            'en_EN': 'en',
            'ko-KR': 'ko',
            'ZH CN': 'zh',
            'EsCH': 'es',
        }
        for key, value in data.items():
            with self.subTest(key):
                self.assertEqual(
                    convert_to_iso_639_1(key),
                    value
                )

    def test_available_languages(self):
        languages_ = list(filter(lambda key: len(key) > 0, languages.keys()))
        gw_languages = (
            'en',
            'zh',
            'es',
            'id',
            'ja',
            'ko',
            'pt',
            'vi',
            'tr',
        )
        for lang in languages_:
            with self.subTest(lang):
                self.assertIn(
                    convert_to_iso_639_1(lang),
                    gw_languages
                )
