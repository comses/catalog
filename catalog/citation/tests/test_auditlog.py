from django.test import TestCase
from django.contrib.auth.models import User
from .. import models


class TestModelManagers(TestCase):
    @classmethod
    def setUpClass(cls):
        super(TestModelManagers, cls).setUpClass()
        cls.user = User.objects.create_user(username="foo", email="a@b.com", password="bar")
        cls.author_detached = {'orcid': '1234', 'type': 'foo', 'given_name': 'Bob', 'family_name': 'Smith'}
        cls.context = models.AuditCommand.objects.create(
            creator=cls.user, action=models.AuditCommand.Action.MANUAL)

    @staticmethod
    def to_dict(instance):
        return {field.column: getattr(instance, field.column) for field in instance._meta.local_fields}

    def check_auditlog(self, user, action, instance, auditlog):
        payload = TestModelManagers.to_dict(instance)
        table = instance._meta.db_table
        self.assertEqual(auditlog.user_id, user.id)
        self.assertEqual(auditlog.table, table)
        self.assertEqual(auditlog.action, action)
        self.assertEqual(auditlog.payload, payload)

    def test_author_log_create(self):
        author = models.Author.objects.log_create(audit_command=self.context, **self.author_detached)
        auditlog = models.AuditLog.objects.first()
        self.assertEqual(auditlog.table, 'author')
        self.assertEqual(auditlog.action, 'INSERT')
        self.assertEqual(auditlog.row_id, author.id)

    def test_author_log_get_or_create(self):
        author, created = models.Author.objects.log_get_or_create(
            audit_command=self.context, **self.author_detached)
        auditlog = models.AuditLog.objects.first()
        self.assertEqual(auditlog.table, 'author')
        self.assertEqual(auditlog.action, 'INSERT')
        self.assertEqual(auditlog.row_id, author.id)

        author2, created = models.Author.objects.log_get_or_create(
            audit_command=self.context, id=author.id, **self.author_detached)
        auditlog2 = models.AuditLog.objects.filter(action='UPDATE').first()
        self.assertEqual(auditlog2, None)

    def test_author_log_update(self):
        models.Author.objects.create(**self.author_detached)
        models.Author.objects.log_update(audit_command=self.context, given_name='Ralph')
        auditlog = models.AuditLog.objects.first()
        self.assertEqual(auditlog.table, 'author')
        self.assertEqual(auditlog.action, 'UPDATE')
        self.assertEqual(auditlog.payload['data']['given_name']['new'], 'Ralph')
        self.assertEqual(auditlog.payload['data']['given_name']['old'], 'Bob')

    def test_author_log_delete(self):
        author = models.Author.objects.create(**self.author_detached)
        author_contents = {'id': author.id, 'orcid': author.orcid, 'type': author.type}
        models.Author.objects.all().log_delete(audit_command=self.context)
        auditlog = models.AuditLog.objects.first()
        self.assertEqual(auditlog.table, 'author')
        self.assertEqual(auditlog.action, 'DELETE')
        # auditlog.payload.pop('name')
        self.assertEqual(auditlog.payload['data']['given_name'], self.author_detached['given_name'])
