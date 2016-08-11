from invoke import task, run
from invoke.tasks import call

import logging
import os
import re

logger = logging.getLogger(__name__)

# # default to current working directory
# env.project_path = os.path.dirname(__file__)
# # needed to push catalog.settings onto the path.
# env.abs_project_path = os.path.abspath(env.project_path)
# sys.path.append(env.abs_project_path)
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
       'ignored_coverage': ('test', 'settings', 'migrations', 'wsgi', 'management'),
       'solr_version': '4.10.4',
       'vcs': 'git'}
env['solr_conf_dir'] = 'solr-{}/example/solr/catalog/conf'.format(env['solr_version'])
env['virtualenv_path'] = '%s/.virtualenvs/%s' % (os.getenv('HOME'), env['project_name'])


# # django integration for access to settings, etc.
# django.project(env.project_name)
# from django.conf import settings as catalog_settings


@task
def clean_update(ctx):
    ctx.run("git fetch --all && git reset --hard origin/master")


@task
def sh(ctx):
    dj('shell_plus --ipython', pty=True)


def dj(command, **kwargs):
    """
    Run a Django manage.py command on the server.
    """
    run_chain('{python} manage.py {dj_command} --settings {project_conf}'.format(dj_command=command, **env),
              **kwargs)


def run_chain(*commands, **kwargs):
    command = ' && '.join(commands)
    run(command, **kwargs)


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
        ignored = ['*{0}*'.format(ignored_pkg) for ignored_pkg in env['ignored_coverage']]
        coverage_cmd = "coverage run --source='.' --omit=" + ','.join(ignored)
    else:
        coverage_cmd = env['python']
    run('{coverage_cmd} manage.py test {apps}'.format(apps=apps, coverage_cmd=coverage_cmd))


@task(pre=[call(test, coverage=True)])
def coverage(ctx):
    ignored = ['*{0}*'.format(ignored_pkg) for ignored_pkg in env['ignored_coverage']]
    ctx.run('coverage html --omit=' + ','.join(ignored))


@task
def server(ctx, ip="0.0.0.0", port=8000):
    dj('runserver {ip}:{port}'.format(ip=ip, port=port), capture=False)


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
    run_chain('dropdb --if-exists {db_name} -U {db_user} -h db '.format(**env),
              'createdb {db_name} -U {db_user} -h db'.format(**env))
    if os.path.isfile(dumpfile):
        logger.debug("loading data from %s", dumpfile)
        run('psql -h db {db_name} {db_user} < {dumpfile}'.format(dumpfile=dumpfile, **env))
    if init_db_schema:
        initialize_database_schema()


@task(aliases=['idb', 'init_db'])
def initialize_database_schema(ctx):
    run_chain('python manage.py makemigrations', 'python manage.py migrate')


@task(aliases=['zi'])
def zotero_import(ctx, group=None, collection=None):
    _command = 'python manage.py zotero_import'
    if group:
        _command += ' --group=%s' % group
    if collection:
        _command += ' --collection=%s' % collection
    run(_command)


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
