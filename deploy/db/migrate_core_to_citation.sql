begin;

TRUNCATE TABLE public.citation_author
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_authoralias
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_container
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_containeralias
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_invitationemailtemplate
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_modeldocumentation
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_note
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_platform
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_publication
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_publicationcitations
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_publicationauthors
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_publicationmodeldocumentations
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_publicationplatforms
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_publicationsponsors
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_publicationtags
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_auditlog
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_raw
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_sponsor
    RESTART IDENTITY
    CASCADE;
TRUNCATE TABLE public.citation_tag
    RESTART IDENTITY
    CASCADE;

insert into citation_author (id, given_name, family_name, type, email, orcid, date_added, date_modified)
  select id, first_name, last_name, 'INDIVIDUAL', '', '', now(), now()
  from core_creator;

insert into citation_authoralias (id, given_name, family_name, author_id)
  select id, first_name, last_name as name, id
  from core_creator;


insert into citation_container (id, name, issn, type, date_added, date_modified)
  select id, name, '', 'Journal Article', now(), now()
  from core_journal;

insert into citation_containeralias (id, name, container_id)
  select id, name, id
  from core_journal;


insert into citation_modeldocumentation (id, name, date_modified, date_added)
  select id, name, now(), now()
  from core_modeldocumentation;


insert into citation_platform (id, name, url, description, date_modified, date_added)
  select id, name, '', '', now(), now()
  from core_platform;


insert into citation_sponsor (id, name, url, description, date_modified, date_added)
  select id, name, '', '', now(), now()
  from core_sponsor;


insert into citation_tag (id, name, date_modified, date_added)
  select id, name, now(), now()
  from core_tag;


insert into citation_publication
  (id, title, abstract, short_title, zotero_key, url, date_published_text, date_published, date_accessed, archive, archive_location, library_catalog, call_number, rights, extra, published_language, zotero_date_added, zotero_date_modified, code_archive_url, contact_author_name, contact_email, status, date_added, date_modified, author_comments, email_sent_count, is_primary, pages, issn, volume, issue, series, series_title, series_text, doi, added_by_id, assigned_curator_id, container_id)
  select id, title, abstract, short_title, zotero_key, url, date_published_text, date_published, date_accessed, archive, archive_location, library_catalog, call_number, rights, extra, published_language, zotero_date_added, zotero_date_modified, coalesce(code_archive_url, ''), contact_author_name, contact_email, status, date_added, date_modified, author_comments, email_sent_count, is_primary, pages, issn, volume, issue, series, series_title, series_text, doi, added_by_id, assigned_curator_id, journal_id
  from core_publication;

insert into citation_note
  (id, text, date_added, date_modified, zotero_key, zotero_date_added, zotero_date_modified, deleted_on, added_by_id, deleted_by_id, publication_id)
  select id, text, date_added, date_modified, zotero_key, zotero_date_added, zotero_date_modified, deleted_on, added_by_id, deleted_by_id, publication_id
  from core_note;

insert into citation_publicationauthors (id, publication_id, author_id, role, date_added, date_modified)
  select id, publication_id, creator_id as author_id, 'AUTHOR', now(), now()
  from core_publication_creators;

insert into citation_publicationmodeldocumentations (id, publication_id, model_documentation_id, date_added, date_modified)
  select id, publication_id, modeldocumentation_id, now(), now()
  from core_publication_model_documentation;

insert into citation_publicationplatforms (id, publication_id, platform_id, date_added, date_modified)
  select id, publication_id, platform_id, now(), now()
  from core_publication_platforms;

insert into citation_publicationsponsors (id, publication_id, sponsor_id, date_added, date_modified)
  select id, publication_id, sponsor_id, now(), now()
  from core_publication_sponsors;

insert into citation_publicationtags (id, publication_id, tag_id, date_added, date_modified)
  select id, publication_id, tag_id, now(), now()
  from core_publication_tags;

select setval('citation_author_id_seq', nextval('core_creator_id_seq'));
select setval('citation_authoralias_id_seq', nextval('core_creator_id_seq'));

select setval('citation_container_id_seq', nextval('core_journal_id_seq'));
select setval('citation_containeralias_id_seq', nextval('core_journal_id_seq'));

select setval('citation_modeldocumentation_id_seq', nextval('core_modeldocumentation_id_seq'));

select setval('citation_platform_id_seq', nextval('core_platform_id_seq'));

select setval('citation_sponsor_id_seq', nextval('core_sponsor_id_seq'));

select setval('citation_tag_id_seq', nextval('core_tag_id_seq'));

select setval('citation_publication_id_seq', nextval('core_publication_id_seq'));
select setval('citation_note_id_seq', nextval('core_note_id_seq'));
select setval('citation_publicationauthors_id_seq', nextval('core_publication_creators_id_seq'));
select setval('citation_publicationmodeldocumentations_id_seq', nextval('core_publication_model_documentation_m2m_id_seq'));
select setval('citation_publicationplatforms_id_seq', nextval('core_publication_platforms_id_seq'));
select setval('citation_publicationsponsors_id_seq', nextval('core_publication_sponsors_id_seq'));
select setval('citation_publicationtags_id_seq', nextval('core_publication_tags_id_seq'));

commit;

-- Another time
-- insert into citation_publicationauditlog (id, creator_id, action, date_added, message, payload)
--   select id, creator_id, action, date_added, message, modified_data
--   from core_publicationauditlog;