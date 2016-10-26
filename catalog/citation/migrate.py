"""Module to migrate external IDs to unique, nullable format. Temporary file. Remove after migration on DB"""

from django.db import connection
from . import models
from .merger import ContainerMergeGroup
from django.contrib.auth.models import User


def merge_issns():
    def select_duplicate_issns():
        cursor = connection.cursor()

        cursor.execute("SELECT issn FROM citation_container WHERE issn <> '' GROUP BY issn HAVING count(issn) > 1;")
        issns = [r[0] for r in cursor.fetchall()]
        print(issns)
        return issns

    issns = select_duplicate_issns()
    creator = User.objects.get(username='alee14')

    for issn in issns:
        print("ISSN: {}".format(issn))

        audit_command = models.AuditCommand(creator=creator, action='MERGE')
        duplicates = list(models.Container.objects.filter(issn=issn).order_by('date_added'))
        print("Other: ".format(set(duplicates[1:])))
        cmg = ContainerMergeGroup.from_list(duplicates)
        if cmg.is_valid():
            cmg.merge(audit_command=audit_command)


def clean_data():
    models.Publication.objects.filter(doi='').update(doi=None)
    models.Publication.objects.filter(isi='').update(isi=None)

    models.Container.objects.filter(issn='').update(issn=None)
    models.Container.objects.filter(eissn='').update(eissn=None)

    models.Author.objects.filter(orcid='').update(orcid=None)
    models.Author.objects.filter(researcherid='').update(researcherid=None)


def run():
    merge_issns()
    clean_data()
