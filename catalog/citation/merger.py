from . import models, util, search_indexes
from django.contrib.auth.models import User
from django.db import connection
from django.db.models import QuerySet, Q, Count
from typing import List, Set
from collections import defaultdict

import textwrap
import logging

logger = logging.getLogger(__name__)


class AuthoritativeAuthorValidationMessage:
    def __init__(self, additional, all):
        self.additional = additional
        self.all = all

    @staticmethod
    def _str_items(items):
        return "\n".join([" - " + str(item) for item in items])

    def __str__(self):
        template = textwrap.dedent(
            """
            Publications related to authors not in merge group:
            {}

            All publications:
            {}""")
        return template.format(self._str_items(self.additional),
                               self._str_items(self.all))


class AuthoritativeAuthorMergeGroupSet:
    """
    Merge authors assuming no final publication author set is authoritative

    This avoids the issue of having to match authors between publications
    which is a hard problem.
    """

    def __init__(self, final, others):
        """
        :param final: final authoritative publication
        :type final: models.Publication
        :param others: Other publications
        :type others: Set[models.Publication]
        """
        self.final = final
        self.others = others

    def __len__(self):
        return len(self.others) + 1

    def __repr__(self):
        return "{}(final={}, others={})".format(
            self.__class__.__name__, repr(self.final), repr(self.others))

    @property
    def errors(self):
        assert hasattr(self, '_is_valid')
        assert not self._is_valid
        return self._errors

    def _check_outside_publications(self):
        all_publications = set(other for other in self.others)
        all_publications.add(self.final)

        outside_merge_group = set()

        for publication in all_publications:
            for author in publication.creators.all():
                author_publications = set(author.publications.all())
                if not all_publications.issuperset(author_publications):
                    outside_merge_group.update(author_publications.difference(all_publications))

        self._errors = AuthoritativeAuthorValidationMessage(additional=outside_merge_group, all=all_publications)

    def is_valid(self):
        """Ensure that authors do not point to any publications outside of the merge group"""
        if hasattr(self, '_is_valid'):
            return self._is_valid

        self._is_valid = True
        return self._is_valid

    def merge(self, audit_command, force=False):
        assert hasattr(self, '_is_valid')
        if not force:
            assert self._is_valid

        all_publications = set(other for other in self.others)
        all_publications.add(self.final)

        for publication in all_publications:
            for author in publication.creators.all():
                if author.publications.count() == 1:
                    author.author_aliases.all().log_delete(audit_command=audit_command)
                    author.log_delete(audit_command=audit_command)
                else:
                    models.PublicationAuthors.objects.filter(author=author).log_delete(audit_command=audit_command)


class AuthorMergeGroup:
    def __init__(self, final: models.Author, others: Set[models.Author]):
        self.final = final
        self.others = others

    def __len__(self):
        return len(self.others) + 1

    def __repr__(self):
        return "{}(final={}, others={})".format(self.__class__.__name__, repr(self.final), repr(self.others))

    def __str__(self):
        pass

    @classmethod
    def from_list(cls, list):
        return cls(final=list[0], others=list[1:])

    def validate_publication_relationships(self):
        """Ensure  that for every publication authored by a publication in the mergegroup
        is authored by no other authors in the merge group
        """

        invalidated_publications = {}

        all_publications = defaultdict(lambda: set())
        for publication in self.final.publications.all():
            all_publications[publication].add(self.final)

        for other in self.others:
            for publication in other.publications.all():
                all_publications[publication].add(other)
                if len(all_publications[publication]) > 1:
                    invalidated_publications[publication] = all_publications[publication]

        return invalidated_publications

    def is_valid(self):
        """Validate a mergeset of authors

        Conditions in which authors can be merged

        1. An author set that is being merged into one author should have ensure that all author in the set of part of
          distinct publications
        """
        if hasattr(self, '_is_valid'):
            return self._is_valid

        self._errors = {}
        relationship_error = self.validate_publication_relationships()
        if relationship_error:
            self._errors['relationship'] = relationship_error

        self._is_valid = not bool(self._errors)

        return self._is_valid

    @property
    def errors(self):
        assert hasattr(self, '_is_valid')
        assert not self._is_valid
        return self._errors

    def merge(self, audit_command: models.AuditCommand, force=False):
        """
        Merges a group of authors into a single author and many author aliases
        """
        assert hasattr(self, '_is_valid')
        if not force:
            assert self._is_valid

        for other in self.others:
            if other.family_name != self.final.family_name or \
                            other.given_name != self.final.given_name:
                models.AuthorAlias.objects.log_get_or_create(
                    audit_command=audit_command,
                    author_id=self.final.id,
                    given_name=other.given_name,
                    family_name=other.family_name)

            author_aliases = other.author_aliases.all()
            for author_alias in author_aliases:
                if not models.AuthorAlias.objects.filter(
                        given_name=author_alias.given_name,
                        family_name=author_alias.family_name,
                        author=self.final).exists():
                    author_alias.log_update(audit_command=audit_command, author_id=self.final.id)
                else:
                    author_alias.log_delete(audit_command=audit_command)

            changes = {}
            for field in ['orcid', 'given_name', 'family_name']:
                if not getattr(self.final, field):
                    changes[field] = getattr(other, field)

            self.final.log_update(audit_command=audit_command, **changes)
            models.RawAuthors.objects.filter(author=other).exclude(
                raw__in=models.Raw.objects.filter(authors__in=[self.final])).log_update(
                audit_command=audit_command, author_id=self.final.id)
            other.log_delete(audit_command=audit_command)


class ContainerMergerValidationMessage:
    def __init__(self, containers, issns):
        self.containers = containers
        self.issns = issns

    @staticmethod
    def _str_item(item):
        return textwrap.indent(str(item), '\t')

    def __str__(self):
        issns = self._str_item(self.issns)
        containers = self._str_item(self.containers)
        template = textwrap.dedent(
            """
            Multiple ISSNs in container merge: {}

            {}""")
        return template.format(issns, containers)


class ContainerMergeGroup:
    def __init__(self, final: models.Container, others: Set[models.Container]):
        self.final = final
        others.discard(final)
        self.others = others

    def __len__(self):
        return len(self.others) + 1

    def __repr__(self):
        return "{}(final={}, others={})".format(self.__class__.__name__, repr(self.final), repr(self.others))

    @classmethod
    def from_list(cls, containers):
        return cls(final=containers[0], others=set(containers[1:]))

    def is_valid(self):
        """Determine if it is safe to merge a set of related containers

        A set of related containers is safe to merge if:

        1. every container with an ISSN has the same ISSN
        """

        issns = set(other.issn for other in self.others if other.issn != '')
        if self.final.issn:
            issns.add(self.final.issn)

        containers = self.others.copy()
        containers.add(self.final)

        self._errors = ContainerMergerValidationMessage(containers=containers,
                                                        issns=issns) if len(issns) > 1 else None
        self._is_valid = len(issns) <= 1
        return self._is_valid

    @property
    def errors(self):
        assert hasattr(self, '_is_valid')
        assert not self._is_valid
        return self._errors

    def merge(self, audit_command: models.AuditCommand, force=False):
        assert hasattr(self, '_is_valid')
        if not force:
            assert self._is_valid

        final_container = self.final
        other_containers = self.others

        models.Publication.objects.filter(container__in=other_containers).log_update(audit_command=audit_command,
                                                                                     container_id=final_container.id)
        for other_container in other_containers:
            if other_container.name != final_container.name:
                models.ContainerAlias.objects.log_get_or_create(
                    audit_command=audit_command,
                    container_id=final_container.id,
                    name=other_container.name)

            container_aliases = other_container.container_aliases.all()
            for container_alias in container_aliases:
                if not models.ContainerAlias.objects.filter(
                        container=final_container,
                        name=container_alias.name).exists():
                    container_alias.log_update(audit_command=audit_command, container_id=final_container.id)
                else:
                    container_alias.log_delete(audit_command=audit_command)

            changes = {}
            for field in ['issn']:
                if not getattr(final_container, field):
                    changes[field] = getattr(other_container, field)

            final_container.log_update(audit_command=audit_command, **changes)
            models.Raw.objects.filter(container=other_container).exclude(
                id__in=models.Raw.objects.filter(container=final_container)).log_update(
                audit_command=audit_command, container_id=final_container.id)
            other_container.log_delete(audit_command=audit_command)


class PublicationMergeValidationMessage:
    def __init__(self, final, others, citation_errors, author_errors, container_errors,
                 publication_errors, publication_author_errors, publication_container_errors):
        self.final = final
        self.others = others
        self.citation_errors = citation_errors
        self.author_errors = author_errors
        self.publication_errors = publication_errors
        self.publication_author_errors = publication_author_errors
        self.container_errors = container_errors
        self.publication_container_errors = publication_container_errors

    @staticmethod
    def _str_item(item):
        return textwrap.indent(str(item), '\t')

    def recompute(self):
        final = models.Publication.objects.get(id=self.final.id)
        if self.final.doi:
            assert final.doi == self.final.doi
        if self.final.isi:
            assert final.isi == self.final.isi
        others = set(final.get_duplicates())
        if others:
            return PublicationMergeGroup(final=self.final, others=others)

    @property
    def authors(self):
        return models.Author.objects.filter(Q(publications__in=self.others) | Q(publications=self.final))

    @property
    def containers(self):
        return models.Container.objects.filter(Q(publications__in=self.others) | Q(publications=self.final))

    def __bool__(self):
        return bool(self.citation_errors) or bool(self.container_errors) or bool(self.publication_errors) or bool(
            self.publication_container_errors) or bool(self.author_errors) or bool(self.publication_author_errors)

    def __str__(self):
        citation_errors = self._str_item(self.citation_errors)
        author_errors = self._str_item(self.author_errors)
        publication_author_errors = self._str_item(self.publication_author_errors)
        container_errors = self._str_item(self.container_errors)
        publication_container_errors = self._str_item(self.publication_container_errors)

        template = textwrap.dedent(
            """
            Publication Merge Errors:

            Duplicate Referenced By Errors:
            {}

                Citation Errors
            {}

                Author Errors
            {}

                Author Publication Errors
            {}

                Container Errors
            {}

                Container Publication Errors
            {}
            """)

        return template.format(
            str(self.publication_errors),
            citation_errors,
            author_errors,
            publication_author_errors,
            container_errors,
            publication_container_errors)


class CitationCountMessage:
    def __init__(self, citation_count_dict):
        self.citation_count_dict = citation_count_dict

    @classmethod
    def from_merge_group(cls, final, others):
        """Determine if citations for a publication merge group are safe to merge.

        Based on the citations a publication merge group is safe to merge if all publications
         with citations have the same number of citations
        """

        all_publications = [other for other in others]
        all_publications.append(final)
        citation_count_dict = {}

        for publication in all_publications:
            citation_count = publication.citations.count()
            citation_count_dict.setdefault(citation_count, []).append(publication)

        return cls(citation_count_dict=citation_count_dict)

    @staticmethod
    def _str_publications(publications):
        return "\n".join("\t\t- {}".format(str(publication)) for publication in publications)

    def __str__(self):
        if self.__bool__():
            return "\n".join("\tCitation Count {}:\n{}" \
                             .format(citation_count, self._str_publications(publications))
                             for citation_count, publications in self.citation_count_dict.items())
        else:
            return str(None)

    def __bool__(self):
        n = len(self.citation_count_dict)
        if 0 in self.citation_count_dict:
            n -= 1

        return n > 1


class ReferencedByMessage:
    def __init__(self, publications):
        self.publications = publications

    def __str__(self):
        if len(self.publications) > 0:
            return "\n".join(" - " + str(p) for p in self.publications)
        else:
            return str(None)

    def __bool__(self):
        return bool(self.publications)


class PublicationMergeGroup:
    def __init__(self, final: models.Publication, others: Set[models.Publication]):
        self.final = final
        others.discard(final)
        self.others = others
        self._errors = PublicationMergeValidationMessage(final=final,
                                                         others=others,
                                                         citation_errors=None,
                                                         author_errors=None,
                                                         container_errors=None,
                                                         publication_errors=None,
                                                         publication_author_errors=None,
                                                         publication_container_errors=None)

        self.container_merge_group = self.create_container_merge_group()
        self.author_merge_group_set = self.create_authoritive_author_merge_group_set()

    def __len__(self):
        return len(self.others) + 1

    def __repr__(self):
        return "{}(final={}, others={})".format(self.__class__.__name__, repr(self.final), repr(self.others))

    def __str__(self):
        template = textwrap.dedent(
            """
            Final Publication:
            {}

            Other Publications:
            {}
            """)
        other_strs = "\n".join(" - " + str(other) for other in self.others)
        return template.format(" - " + str(self.final), other_strs)

    @classmethod
    def from_list(cls, l):
        final, others = cls._find_authoritative(l)
        return cls(final=final, others=others)

    @staticmethod
    def _find_authoritative(l: List):
        """
        Make the first primary publication authoritative, otherwise just use the first publication
        """
        for i, publication in enumerate(l):
            if publication.is_primary:
                publist_copy = l.copy()
                return publist_copy.pop(i), set(publist_copy)

        return l[0], set(l[1:])

    def different_final(self, new_final):
        new_others = self.others.copy()
        if new_final not in new_others:
            raise ValueError("Authoritative record must be in 'other' set")
        new_others.discard(new_final)
        new_others.add(self.final)
        return PublicationMergeGroup(final=new_final, others=new_others)

    def create_authoritive_author_merge_group_set(self) -> AuthoritativeAuthorMergeGroupSet:
        """Create Author merge groups ignoring non authoritative others"""
        return AuthoritativeAuthorMergeGroupSet(final=self.final, others=self.others)

    def all_authors(self):
        authors = set()

        final_authors = self.final.creators.all()
        authors.update([final_author for final_author in final_authors])

        for other in self.others:
            other_authors = other.creators.all()
            authors.update([other_author for other_author in other_authors])

        return authors

    # def is_valid_author_merge_group_set_for_publication_merge_group(self):
    #     authors = self.all_authors()
    #     merge_group_authors = set()
    #     for author_merge_group in self.author_merge_group_set:
    #         merge_group_authors.add(author_merge_group)
    #         merge_group_authors.update([other.id for other in author_merge_group.others])
    #
    #     valid = authors == merge_group_authors
    #     if not valid:
    #         missing_authors = authors.difference(merge_group_authors)
    #         additional_authors = merge_group_authors.difference(authors)
    #         self._errors.publication_author_errors = {
    #             'additional': additional_authors,
    #             'missing': missing_authors}
    #     return valid

    def create_container_merge_group(self, final_container=None, other_containers=None) -> ContainerMergeGroup:
        if final_container is None and other_containers is None:
            final_container = self.final.container
            other_containers = set(other.container for other in self.others)

        return ContainerMergeGroup(final=final_container, others=other_containers)

    def all_containers(self):
        all_containers = set(other.container for other in self.others)
        all_containers.add(self.final.container)
        return all_containers

    def is_valid_container_merge_group_for_publication_merge_group(self):
        all_containers = self.all_containers()

        all_containers_in_merge_group = set(self.container_merge_group.others)
        all_containers_in_merge_group.add(self.container_merge_group.final)

        valid = all_containers_in_merge_group == all_containers
        if not valid:
            additional_containers = all_containers_in_merge_group.difference(all_containers)
            missing_containers = all_containers.difference(all_containers_in_merge_group)
            self._errors.publication_container_errors = {
                'additional': additional_containers,
                'missing': missing_containers}

        return valid

    def is_valid_each_referenced_by_distinct(self):
        """If more than one publication in the merge group if referenced by a merge group that is an error"""
        referenced_publications = defaultdict(lambda: 0)
        for referenced_by in self.final.referenced_by.all():
            referenced_publications[referenced_by] += 1

        for other in self.others:
            for referenced_by in other.referenced_by.all():
                referenced_publications[referenced_by] += 1

        problematic_references = set(p for p, v in referenced_publications.items() if v > 1)
        self._errors.publication_errors = ReferencedByMessage(problematic_references)
        return bool(self._errors.publication_errors)

    def _move_citations(self):
        pass

    def is_valid(self):
        if hasattr(self, '_is_valid'):
            return self._is_valid

        valid = True

        self._errors.citation_errors = CitationCountMessage.from_merge_group(final=self.final, others=self.others)
        self.is_valid_each_referenced_by_distinct()

        if not self.container_merge_group.is_valid():
            self._errors.container_errors = self.container_merge_group.errors

        self.is_valid_container_merge_group_for_publication_merge_group()

        if not self.author_merge_group_set.is_valid():
            self._errors.author_errors = self.author_merge_group_set.errors

        if self.author_merge_group_set is None or self.container_merge_group is None:
            valid = False

        self._is_valid = valid and not bool(self._errors)
        return self._is_valid

    def _delete_deletable_citations(self, other: models.Publication, audit_command):
        deletable_citations = other.citations.annotate(n_referenced_by=Count('referenced_by')) \
            .filter(is_primary=False, n_referenced_by=1)
        models.Raw.objects.filter(publication__in=deletable_citations).log_delete(audit_command=audit_command)
        deletable_citations.log_delete(audit_command=audit_command)

    @property
    def errors(self):
        assert hasattr(self, '_is_valid'), 'Must call "is_valid()" method before finding errors'
        assert not self._is_valid, 'PublicationMergeGroup is valid. Must be invalid to have errors'

        return self._errors

    def merge(self,
              audit_command: models.AuditCommand,
              force=False):
        """
        Merge publications into one final publication

        This merge is more complex than the Author and Container merges because it merges
        the related author and container models. Citation from other instances are ignored unless
        the final instance has no citations, in which case citations are moved over from an arbitrary
        other publication
        """

        assert hasattr(self, '_is_valid'), 'Must call "is_valid()" method before calling merge'
        if not force:
            assert self._is_valid, 'PublicationMergeGroup is not valid. Must be valid to merge'

        self.author_merge_group_set.merge(audit_command=audit_command, force=force)
        self.container_merge_group.merge(audit_command=audit_command, force=force)

        models.Raw.objects \
            .filter(publication__in=self.others) \
            .log_update(audit_command=audit_command, publication_id=self.final.id)

        changes = {}
        for publication in self.others:
            for field in ['date_published_text', 'title', 'doi', 'abstract', 'isi']:
                if not getattr(self.final, field):
                    changes[field] = getattr(publication, field)

        for other in self.others:
            self._delete_deletable_citations(other, audit_command)

        self.final.log_update(audit_command, **changes)
        models.Publication.objects.filter(id__in=[other.id for other in self.others]) \
            .log_delete(audit_command)

        self._move_citations()


def display_merge_publications(publications):
    print("Merged")
    for publication in publications:
        print("\tYear: {}, Title: {}, DOI: {}".format(publication.date_published_text, publication.title,
                                                      publication.doi))
    print("\n")
