from invoke import task
from invoke.tasks import call

import logging
import os
import re
import sys


# push current working directory onto the path to access catalog.settings
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ['DJANGO_SETTINGS_MODULE'] = 'catalog.settings'

#
# # default env configuration
# env.roledefs = {
#     'localhost': ['localhost'],
#     'staging': ['dev-catalog.comses.net'],
#     'prod': ['catalog.comses.net'],
# }
env = {'python': 'python3',
       'project_name': 'catalog',
       'project_conf': 'catalog.settings',
       'db_user': 'catalog',
       'db_name': 'comses_catalog',
       'database': 'default',
       'coverage_omit_patterns': ('test', 'settings', 'migrations', 'wsgi', 'management', 'tasks'),
       'solr_version': '4.10.4',
       'vcs': 'git'}
env['solr_conf_dir'] = 'solr-{}/example/solr/catalog/conf'.format(env['solr_version'])
env['virtualenv_path'] = '%s/.virtualenvs/%s' % (os.getenv('HOME'), env['project_name'])

logger = logging.getLogger(__name__)

# # django integration for access to settings, etc.
# django.project(env.project_name)
# from django.conf import settings as catalog_settings


@task
def clean_update(ctx):
    ctx.run("git fetch --all && git reset --hard origin/master")


@task
def sh(ctx):
    dj(ctx, 'shell_plus --ipython', pty=True)


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
        ctx.run('python manage.py clean_data --file catalog/citation/migrations/clean_data/{datafile} --creator={creator}'.format(datafile=d, creator=creator))
    print("Merging")
    datafiles = ['sponsor.merge', 'platform.merge', 'model_documentation.merge']
    for d in datafiles:
        ctx.run('python manage.py clean_data --file catalog/citation/migrations/clean_data/{datafile} --creator={creator}'.format(datafile=d, creator=creator))
    print("Deleting")
    datafiles = ['sponsor.delete', 'platform.delete']
    for d in datafiles:
        ctx.run('python manage.py clean_data --file catalog/citation/migrations/clean_data/{datafile} --creator={creator}'.format(datafile=d, creator=creator))

@task
def setup_solr(ctx, travis=False):
    if travis:
        path = 'solr-{solr_version}/example/multicore'.format(**env)
    else:
        path = 'solr-{solr_version}/example/solr'.format(**env)
    catalog_path = '{}/catalog'.format(path)
    collection1_path = 'solr-{solr_version}/example/solr/collection1'.format(**env)
    if not os.path.exists('{}/conf'.format(catalog_path)):
        os.makedirs('{}/conf'.format(catalog_path), exist_ok=True)
        run_chain(
            'cp deploy/vagrant/core.properties {}/.'.format(catalog_path),
            'cp -r {collection1_path}/conf {catalog_path}'.format(collection1_path=collection1_path,
                                                                  catalog_path=catalog_path))
    run_chain('{python} manage.py build_solr_schema > schema.xml'.format(**env),
              'cp schema.xml {catalog_path}/conf/.'.format(catalog_path=catalog_path))


@task(aliases=['rfd'])
def restore_from_dump(ctx, dumpfile='catalog.sql', init_db_schema=True):
    from django.conf import settings
    pgpass_path = os.path.join(os.path.expanduser('~'), '.pgpass')
    with open(pgpass_path, 'w+') as pgpass:
        pgpass.write('db:*:template1:{db_user}:{db_password}\n'.format(db_password=settings.DATABASES['default']['PASSWORD'], **env))
        pgpass.write('db:*:{db_name}:{db_user}:{db_password}\n'.format(db_password=settings.DATABASES['default']['PASSWORD'], **env))
        ctx.run('chmod 0600 ~/.pgpass')

    ctx.run('dropdb -w --if-exists -e {db_name} -U {db_user} -h db'.format(**env), echo=True, warn=True)
    ctx.run('createdb -w {db_name} -U {db_user} -h db'.format(**env), echo=True, warn=True)
    if os.path.isfile(dumpfile):
        logger.debug("loading data from %s", dumpfile)
        ctx.run('psql -w -q -h db {db_name} {db_user} < {dumpfile}'.format(dumpfile=dumpfile, **env),
                warn=True)
    if init_db_schema:
        initialize_database_schema(ctx)


@task(aliases=['idb', 'init_db'])
def initialize_database_schema(ctx):
    ctx.run('python manage.py makemigrations')
    ctx.run('yes | python manage.py migrate')


@task(aliases=['zi'])
def zotero_import(ctx, group=None, collection=None):
    _command = 'python manage.py zotero_import'
    if group:
        _command += ' --group=%s' % group
    if collection:
        _command += ' --collection=%s' % collection
    ctx.run(_command)


@task(aliases=['ri'])
def rebuild_index(ctx, noinput=False):
    cmd = 'python manage.py rebuild_index'
    if noinput:
        cmd += ' --noinput'
    ctx.run(cmd)


@task
def createuser(ctx):
    ctx.run("createuser {db_user} -rd -U postgres".format(**env))


@task
def createdb(ctx):
    ctx.run("createdb {db_name} -U {db_user}".format(**env))


@task(createuser, createdb)
def setup_postgres(ctx):
    print("Postgres user {db_user} and db {db_name} created.".format(**env))


@task(setup_postgres, initialize_database_schema, zotero_import, setup_solr, rebuild_index)
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
