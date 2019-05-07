import logging
import os
import re
import sys

from invoke import task
from invoke.tasks import call

# push current working directory onto the path to access catalog.settings
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'catalog.settings.dev'

from django.conf import settings

env = {
    'python': 'python3',
    'project_name': 'catalog',
    'project_conf': os.environ['DJANGO_SETTINGS_MODULE'],
    'db_name': settings.DATABASES['default']['NAME'],
    'db_host': settings.DATABASES['default']['HOST'],
    'db_user': settings.DATABASES['default']['USER'],
    'coverage_omit_patterns': ('test', 'settings', 'migrations', 'wsgi', 'management', 'tasks', 'apps.py'),
}

logger = logging.getLogger(__name__)


@task
def clean_update(ctx):
    ctx.run("git fetch --all && git reset --hard origin/master")


@task
def sh(ctx, print_sql=False):
    py_shell = 'shell_plus --ipython'
    if print_sql:
        py_shell += ' --print-sql'
    dj(ctx, py_shell, pty=True)


def dj(ctx, command, **kwargs):
    """
    Run a Django manage.py command on the server.
    """
    ctx.run('{python} manage.py {dj_command} --settings {project_conf}'.format(dj_command=command, **env),
            **kwargs)


def run_chain(ctx, *commands, **kwargs):
    command = ' && '.join(commands)
    ctx.run(command, **kwargs)


@task
def host_type(ctx):
    ctx.run('uname -a')


@task
def test(ctx, name=None, coverage=False):
    if name is not None:
        apps = name
    else:
        apps = ''
    if coverage:
        ignored = ['*{0}*'.format(ignored_pkg) for ignored_pkg in env['coverage_omit_patterns']]
        coverage_cmd = "coverage run --source='catalog' --omit=" + ','.join(ignored)
    else:
        coverage_cmd = env['python']
    ctx.run('{coverage_cmd} manage.py test {apps}'.format(apps=apps, coverage_cmd=coverage_cmd))


@task(pre=[call(test, coverage=True)])
def coverage(ctx):
    ctx.run('coverage html')


@task
def server(ctx, ip="0.0.0.0", port=8000):
    dj('runserver {ip}:{port}'.format(ip=ip, port=port), capture=False)


@task(aliases=['cd'])
def clean_data(ctx, creator=None):
    if creator is None:
        creator = 'cpritch3'
    """ one-off to clean degenerate data in Sponsor, Platform, ModelDocumentation """
    print("Splitting")
    datafiles = ['sponsor.split', 'platform.split']
    for d in datafiles:
        ctx.run('{python} manage.py clean_data --file catalog/citation/migrations/clean_data/{datafile} --creator={creator}'.format(datafile=d, creator=creator, **env))
    print("Merging")
    datafiles = ['sponsor.merge', 'platform.merge', 'model_documentation.merge']
    for d in datafiles:
        ctx.run('{python} manage.py clean_data --file catalog/citation/migrations/clean_data/{datafile} --creator={creator}'.format(datafile=d, creator=creator, **env))
    print("Deleting")
    datafiles = ['sponsor.delete', 'platform.delete']
    for d in datafiles:
        ctx.run('{python} manage.py clean_data --file catalog/citation/migrations/clean_data/{datafile} --creator={creator}'.format(datafile=d, creator=creator, **env))

@task(aliases=['rdb', 'resetdb'])
def reset_database(ctx):
    create_pgpass_file(ctx)
    ctx.run('psql -h {db_host} -c "alter database {db_name} connection limit 1;" -w {db_name} {db_user}'.format(**env),
            echo=True, warn=True)
    ctx.run('psql -h {db_host} -c "select pg_terminate_backend(pid) from pg_stat_activity where datname=\'{db_name}\'" -w {db_name} {db_user}'.format(**env),
            echo=True, warn=True)
    ctx.run('dropdb -w --if-exists -e {db_name} -U {db_user} -h {db_host}'.format(**env), echo=True, warn=True)
    ctx.run('createdb -w {db_name} -U {db_user} -h {db_host}'.format(**env), echo=True, warn=True)


@task(aliases=['rfd'])
def restore_from_dump(ctx, dumpfile='catalog.sql', init_db_schema=True, force=False):
    import django
    django.setup()
    from citation.models import Publication
    number_of_publications = 0
    try:
        number_of_publications = Publication.objects.count()
    except:
        pass
    if number_of_publications > 0 and not force:
        print("Ignoring restore, database with {0} publications already exists. Use --force to override.".format(number_of_publications))
    else:
        reset_database(ctx)
        if os.path.isfile(dumpfile):
            logger.debug("loading data from %s", dumpfile)
            ctx.run('psql -w -q -h db {db_name} {db_user} < {dumpfile}'.format(dumpfile=dumpfile, **env),
                    warn=True)
    if init_db_schema:
        initialize_database_schema(ctx)


@task(aliases=['pgpass'])
def create_pgpass_file(ctx, force=False):
    pgpass_path = os.path.join(os.path.expanduser('~'), '.pgpass')
    if os.path.isfile(pgpass_path) and not force:
        return
    with open(pgpass_path, 'w+') as pgpass:
        db_password = settings.DATABASES['default']['PASSWORD']
        pgpass.write('db:*:*:{db_user}:{db_password}\n'.format(db_password=db_password, **env))
        ctx.run('chmod 0600 ~/.pgpass')


@task
def backup(ctx, path='/backups/postgres'):
    create_pgpass_file(ctx)
    ctx.run('autopostgresqlbackup -c /code/deploy/db/autopgsqlbackup.conf')


@task(aliases=['idb', 'init_db'])
def initialize_database_schema(ctx):
    ctx.run('{python} manage.py makemigrations'.format(**env))
    ctx.run('yes | {python} manage.py migrate'.format(**env))


@task(aliases=['zi'])
def zotero_import(ctx, group=None, collection=None):
    _command = '{python} manage.py zotero_import'
    if group:
        _command += ' --group=%s' % group
    if collection:
        _command += ' --collection=%s' % collection
    ctx.run(_command.format(**env))


@task(aliases=['ri:solr'])
def rebuild_solr_index(ctx, noinput=False):
    cmd = '{python} manage.py rebuild_index'
    if noinput:
        cmd += ' --noinput'
    ctx.run(cmd.format(**env))


@task(aliases=['ri:es'])
def rebuild_elasticsearch_index(ctx):
    import django
    django.setup()
    from catalog.core.search_indexes import bulk_index_public
    bulk_index_public()


@task(aliases=['ri'], pre=[call(rebuild_solr_index, noinput=True), rebuild_elasticsearch_index])
def rebuild_index(ctx):
    pass


@task
def createuser(ctx):
    ctx.run("createuser {db_user} -rd -U postgres".format(**env))


@task
def createdb(ctx):
    ctx.run("createdb {db_name} -U {db_user}".format(**env))


@task(createuser, createdb)
def setup_postgres(ctx):
    print("Postgres user {db_user} and db {db_name} created.".format(**env))


@task(setup_postgres, initialize_database_schema, zotero_import, rebuild_index)
def setup(ctx):
    print("Omnibus setup invoked.")


@task(aliases=['relu'])
def reload_uwsgi(ctx):
    status_line = ctx.run("sudo supervisorctl status | grep {project_name}".format(**env))
    m = re.search('RUNNING(?:\s+)pid\s(\d+)', status_line)
    if m:
        uwsgi_pid = m.group(1)
        logger.debug("sending HUP to %s", uwsgi_pid)
        ctx.run("sudo kill -HUP {}".format(uwsgi_pid))
    else:
        logger.warning("No pid found: %s", status_line)
