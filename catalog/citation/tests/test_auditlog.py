from django.test import TestCase
from django.contrib.auth.models import User
from .. import models


class TestModelManagers(TestCase):
    @classmethod
    def setUpClass(cls):
        super(TestModelManagers, cls).setUpClass()
        cls.user = User.objects.create_user(username="foo", email="a@b.com", password="bar")
        cls.author_detached = {'orcid': '1234', 'type': 'foo', 'primary_given_name': 'Bob', 'primary_family_name': 'Smith'}
        cls.context = models.AuditCommand.objects.create(
            creator=cls.user, action=models.AuditCommand.Action.MANUAL, role=models.AuditCommand.Role.SYSTEM_LOG)

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
        self.assertEqual(auditlog.table, 'citation_author')
        self.assertEqual(auditlog.action, 'INSERT')
        self.assertEqual(auditlog.row_id, author.id)

    def test_author_log_get_or_create(self):
        author, created = models.Author.objects.log_get_or_create(
            audit_command=self.context, **self.author_detached)
        auditlog = models.AuditLog.objects.first()
        self.assertEqual(auditlog.table, 'citation_author')
        self.assertEqual(auditlog.action, 'INSERT')
        self.assertEqual(auditlog.row_id, author.id)

        author2, created = models.Author.objects.log_get_or_create(
            audit_command=self.context, id=author.id, **self.author_detached)
        auditlog2 = models.AuditLog.objects.filter(action='UPDATE').first()
        self.assertEqual(auditlog2.table, 'citation_author')
        self.assertEqual(auditlog2.action, 'UPDATE')
        auditlog2.payload.pop('id')
        self.assertEqual(auditlog2.payload, self.author_detached)

    def test_author_log_update(self):
        models.Author.objects.create(**self.author_detached)
        models.Author.objects.log_update(audit_command=self.context, primary_given_name='Ralph')
        auditlog = models.AuditLog.objects.first()
        self.assertEqual(auditlog.table, 'citation_author')
        self.assertEqual(auditlog.action, 'UPDATE')
        self.assertEqual(auditlog.payload['primary_given_name'], 'Bob') # previous state is recorded

    def test_author_log_delete(self):
        author = models.Author.objects.create(**self.author_detached)
        author_contents = {'id': author.id, 'orcid': author.orcid, 'type': author.type}
        models.Author.objects.all().log_delete(audit_command=self.context)
        auditlog = models.AuditLog.objects.first()
        self.assertEqual(auditlog.table, 'citation_author')
        self.assertEqual(auditlog.action, 'DELETE')
        auditlog.payload.pop('id')
        auditlog.payload.pop('date_added')
        auditlog.payload.pop('date_modified')
        auditlog.payload.pop('email')
        # auditlog.payload.pop('primary_name')
        self.assertEqual(auditlog.payload, self.author_detached)

    # def test_undo_author(self):
    #     models.Author.objects.log_create(context=self.context, payload=self.author_detached)
    #     self.assertEqual(models.Author.objects.count(), 1)
    #     self.assertEqual(models.AuditLog.objects.count(), 1)
    #     auditlogInsert = models.AuditLog.objects.first()
    #
    #     models.Author.objects.log_update(creator_type='INDIVIDUAL')
    #     auditlogUpdate = models.AuditLog.objects.filter(payload__creator_type='INDIVIDUAL').first()
    #     self.assertNotEqual(auditlogUpdate, None)
    #
    #     auditlogInsert.undo()
    #     self.assertEqual(models.Author.objects.count(), 0)
    #     self.assertEqual(models.AuditLog.objects.count(), 5)
