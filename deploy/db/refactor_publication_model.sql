-- How to apply this refactor
-- 1. Delete all migration files
-- 2. Run this script
-- 3. Run `./manage.py migrate core --fake-initial

-- Add the missing columns
ALTER TABLE core_publication 
	ADD COLUMN journal_id int;
ALTER TABLE core_publication 
	ADD COLUMN doi varchar(255);
ALTER TABLE core_publication 
	ADD COLUMN series_text varchar(255);
ALTER TABLE core_publication 
	ADD COLUMN series_title varchar(255);
ALTER TABLE core_publication 
	ADD COLUMN series varchar(255);
ALTER TABLE core_publication 
	ADD COLUMN issue varchar(255);
ALTER TABLE core_publication 
	ADD COLUMN volume varchar(255);
ALTER TABLE core_publication 
	ADD COLUMN issn varchar(255);
ALTER TABLE core_publication 
	ADD COLUMN pages varchar(255);

-- Move Journal Article data into Publication table
UPDATE core_publication SET 
	journal_id = ja.journal_id,
	doi = ja.doi,
	series_text = ja.series_text,
	series_title = ja.series_title,
	series = ja.series,
	issue = ja.issue,
	volume = ja.volume,
	issn = ja.issn,
	pages = ja.pages
	FROM core_journalarticle as ja
	WHERE core_publication.id = ja.publication_ptr_id;

-- Set added columns to be not null temporarily to check that data was 1:1
ALTER TABLE core_publication 
	ALTER COLUMN journal_id SET NOT NULL,
	ALTER COLUMN doi SET NOT NULL,
	ALTER COLUMN series_text SET NOT NULL,
	ALTER COLUMN series_title SET NOT NULL,
	ALTER COLUMN series SET NOT NULL,
	ALTER COLUMN issue SET NOT NULL,
	ALTER COLUMN volume SET NOT NULL,
	ALTER COLUMN issn SET NOT NULL,
	ALTER COLUMN pages SET NOT NULL;

ALTER TABLE core_publication 
	ALTER COLUMN journal_id DROP NOT NULL,
	ALTER COLUMN doi DROP NOT NULL,
	ALTER COLUMN series_text DROP NOT NULL,
	ALTER COLUMN series_title DROP NOT NULL,
	ALTER COLUMN series DROP NOT NULL,
	ALTER COLUMN issue DROP NOT NULL,
	ALTER COLUMN volume DROP NOT NULL,
	ALTER COLUMN issn DROP NOT NULL,
	ALTER COLUMN pages DROP NOT NULL;

-- Add Foreign Key Contraint to publication table
ALTER TABLE core_publication
	ADD CONSTRAINT core_publication_fk_journal_id 
		FOREIGN KEY (journal_id) REFERENCES core_journal(id) 
		DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE core_publication ADD CONSTRAINT core_publication_fk_journal_id  FOREIGN KEY (journal_id) REFERENCES core_journal(id) DEFERRABLE INITIALLY DEFERRED;
-- Delete the old Journal Article Table
DROP TABLE core_journalarticle;

DELETE FROM django_migrations
	WHERE app = 'core';
