from django.test import TestCase
from ..bibtex import ref as bibtex_ref_api, entry as bibtex_entry_api
from .. import ingest, merger, models, util
from django.contrib.auth.models import User

import ast


class TestAuthorStr(TestCase):
    def test_author_str_and_seperated(self):
        author_str = 'Murray-Rust, D. and Brown, C. and van Vliet, J. and Alam, S. J. and\nRobinson, D. T. and Verburg, P. H. and Rounsevell, M.'
        author_split = bibtex_entry_api.guess_author_str_split(author_str)
        self.assertEqual(author_split[1:3], ["Brown, C.", "van Vliet, J."])


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
        audit_command = models.AuditCommand.objects.create(
            role=models.AuditCommand.Role.CURATOR_EDIT,
            action=models.AuditCommand.Action.LOAD,
            creator=user)
        publication = bibtex_entry_api.process(entry=self.walderr2013, audit_command=audit_command)
        names = [a.name for a in models.AuthorAlias.objects.all()]
        self.assertTrue("ABBOTT A" in names)
        self.assertTrue("WALDHERR ANNIE" in names)
        self.assertTrue("WIJERMANS NANDA" in names)


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

        last_name_and_initial_str = util.last_name_and_initial(last_name_and_initials_str)
        self.assertEqual(last_name_and_initial_str, "ABBAS A")
