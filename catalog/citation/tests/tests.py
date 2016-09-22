from django.test import TestCase
from ..bibtex import ref as bibtex_ref_api, entry as bibtex_entry_api
from .. import merger, models, util
from django.contrib.auth.models import User

import ast


class TestAuthorParsing(TestCase):
    def test_author_str_and_seperated(self):
        author_str = 'Murray-Rust, D. and Brown, C. and van Vliet, J. and Alam, S. J. and\nRobinson, D. T. and Verburg, P. H. and Rounsevell, M.'
        author_split = bibtex_entry_api.guess_author_str_split(author_str)
        self.assertEqual(author_split[1:3], [("Brown",  "C"), ("van", "Vliet J")])

    def test_orcid_numbers_str_split(self):
        orcid_numbers_str = """Chu, Eric/0000-0002-5648-6615
   Chu, Eric/0000-0002-5648-6615
   Gallagher, Daniel/0000-0001-7291-5558"""
        orcid_numbers_split = bibtex_entry_api.guess_orcid_numbers_str_split(orcid_numbers_str)
        self.assertEqual([("0000-0002-5648-6615", "Chu", "Eric"),
                          ("0000-0002-5648-6615", "Chu", "Eric"),
                          ("0000-0001-7291-5558", "Gallagher", "Daniel")],
                         orcid_numbers_split)

    def test_researcherid_str_split(self):
        researcherid_numbers_str = """Chu, Eric/B-6509-2015
   Chu, Eric/O-6464-2015
   """
        researcherid_numbers_split = bibtex_entry_api.guess_researcherid_str_split(researcherid_numbers_str)
        self.assertEqual([("B-6509-2015", "Chu", "Eric"),
                          ("O-6464-2015", "Chu", "Eric")],
                         researcherid_numbers_split)

    def test_author_email_str_split(self):
        author_email_str = """pierre.livet@univ-amu.fr
   denis.phan@cnrs.fr
   lena.sanders@parisgeo.cnrs.fr"""
        author_email_split = bibtex_entry_api.guess_author_email_str_split(author_email_str)
        self.assertEqual(["pierre.livet@univ-amu.fr", "denis.phan@cnrs.fr", "lena.sanders@parisgeo.cnrs.fr"],
                         author_email_split)

class TestCitationParsing(TestCase):
    def test_wifi_tracking_solu(self):
        ref = "1 WIFI TRACKING SOLU."
        author_str, year_str, container_str = bibtex_ref_api.guess_elements(ref)
        self.assertEqual(author_str, ref)

    def test_pappalardo(self):
        ref = "1 Pappalardo F., 2011, BMC CANC UNPUB."
        author_str, year_str, container_str = bibtex_ref_api.guess_elements(ref)
        self.assertEqual(author_str, "1 Pappalardo F.")
        self.assertEqual(year_str, "2011")
        self.assertEqual(container_str, "BMC CANC UNPUB.")

    def test_intelligent_agents(self):
        ref = "2002, INTELLIGENT AGENTS C, V10, P325."
        author_str, year_str, container_str = bibtex_ref_api.guess_elements(ref)
        self.assertEqual(author_str, "")
        self.assertEqual(year_str, "2002")
        self.assertEqual(container_str, "INTELLIGENT AGENTS C")


class TestPublication(TestCase):
    @classmethod
    def setUpClass(cls):
        super(TestPublication, cls).setUpClass()
        with open("catalog/citation/tests/data/problematic_entries", "r") as f:
            contents = f.readlines()

        cls.walderr2013 = ast.literal_eval(contents[0])
        cls.galente2012 = ast.literal_eval(contents[1])


class TestEntryParsing(TestPublication):
    def test_walderr2013(self):
        user = User.objects.create_user(username='bar', email='a@b.com', password='test')
        publication = bibtex_entry_api.process(entry=self.walderr2013, creator=user)
        names = [(a.family_name, a.given_name) for a in models.Author.objects.all()]
        self.assertIn(("Waldherr", "Annie"), names)
        self.assertIn(("Wijermans", "Nanda"), names)


class TestNameNormalization(TestCase):
    def test_normalize_name(self):
        abbas_plain = "Abbas AK"
        abbas_period = "Abbas A. K."
        abbas_caps = "ABBAS AK"
        abbas_caps_no_middle = "ABBAS A"
        abbas_comma = "Abbas, AK"
        abbas_full = "Abbas, Alfred K"

        normalized_name = util.normalize_name(abbas_plain)
        self.assertEqual(normalized_name, util.normalize_name(abbas_caps))
        self.assertEqual(normalized_name, util.normalize_name(abbas_comma))

        last_name_and_initials_str = util.last_name_and_initials(normalized_name)
        self.assertEqual(last_name_and_initials_str,
                         util.last_name_and_initials(
                             util.normalize_name(abbas_period)
                         ))
        self.assertNotEqual(last_name_and_initials_str,
                            util.last_name_and_initials(
                                util.normalize_name(abbas_caps_no_middle)
                            ))
        self.assertEqual(last_name_and_initials_str,
                         util.last_name_and_initials(
                             util.normalize_name(abbas_full)
                         ))

        last_name_and_initial_str = util.last_name_and_initial(" ".join(last_name_and_initials_str))
        self.assertEqual(last_name_and_initial_str, "ABBAS A")
