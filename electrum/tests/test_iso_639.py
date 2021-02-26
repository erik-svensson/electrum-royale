from unittest import TestCase

from electrum.i18n import get_iso_639_1, languages


class TestISO639(TestCase):
    def test_lowercase(self):
        self.assertEqual(
            get_iso_639_1('EN'),
            'en'
        )
        self.assertEqual(
            get_iso_639_1('Es'),
            'es'
        )

    def test_less_than_2_letters(self):
        self.assertEqual(
            get_iso_639_1(''),
            ''
        )
        self.assertEqual(
            get_iso_639_1('X'),
            'x'
        )
        self.assertEqual(
            get_iso_639_1('y'),
            'y'
        )

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
                    get_iso_639_1(key),
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
                    get_iso_639_1(lang),
                    gw_languages
                )
