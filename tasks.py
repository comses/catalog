import logging
import os
import sys

from invoke import task
from invoke.tasks import call

# push current working directory onto the path to access catalog.settings
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'catalog.settings.dev')

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
    dj(ctx, 'runserver {ip}:{port}'.format(ip=ip, port=port), capture=False)


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

@task(aliases=['idb', 'init_db'])
def initialize_database_schema(ctx):
    ctx.run('{python} manage.py makemigrations'.format(**env))
    ctx.run('yes | {python} manage.py migrate'.format(**env))


@task(aliases=['cm'])
def check_migrations(ctx):
    """CI/test gate: fail if model changes lack migration files.

    Runs `manage.py makemigrations --check --dry-run`, which exits
    non-zero when new migrations would be generated. Test validation
    must never write migration files as a side effect; run
    `invoke idb` (or manage.py makemigrations) in a development
    environment to create them, then commit the result.
    """
    dj(ctx, 'makemigrations --check --dry-run')


@task
def migrate(ctx):
    """Apply the committed migrations (never generates new ones)."""
    ctx.run('yes | {python} manage.py migrate --settings {project_conf}'.format(**env))


@task(aliases=['zi'])
def zotero_import(ctx, group=None, collection=None):
    _command = '{python} manage.py zotero_import'
    if group:
        _command += ' --group=%s' % group
    if collection:
        _command += ' --collection=%s' % collection
    ctx.run(_command.format(**env))


@task(aliases=['ri', 'ri:es'])
def rebuild_elasticsearch_index(ctx):
    import django
    django.setup()
    from catalog.core.search_indexes import bulk_index_all
    bulk_index_all()
