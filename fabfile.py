from fabric.api import local, sudo, cd, env, lcd, execute, hosts, roles, task, run
from fabric.context_managers import prefix
from fabric.contrib import django, console
from fabric.contrib.project import rsync_project
import logging
import os
import re
import sys

logger = logging.getLogger(__name__)

# default to current working directory
env.project_path = os.path.dirname(__file__)
# needed to push catalog.settings onto the path.
env.abs_project_path = os.path.abspath(env.project_path)
sys.path.append(env.abs_project_path)

# default env configuration
env.roledefs = {
    'localhost': ['localhost'],
    'staging': ['dev-catalog.comses.net'],
    'prod': ['catalog.comses.net'],
}
env.python = 'python'
env.project_name = 'catalog'
env.project_conf = 'catalog.settings'
env.deploy_user = 'nginx'
env.deploy_group = 'comses'
env.database = 'default'
env.deploy_parent_dir = '/opt/'
env.git_url = 'https://github.com/comses/catalog.git'
env.docs_path = os.path.join(env.project_path, 'docs')
env.virtualenv_path = '%s/.virtualenvs/%s' % (os.getenv('HOME'), env.project_name)
env.ignored_coverage = ('test', 'settings', 'migrations', 'fabfile', 'wsgi', 'management')
env.solr_conf_dir = '/etc/solr/conf'
env.db_user = 'catalog'
env.db_name = 'comses_catalog'
env.vcs = 'git'

# django integration for access to settings, etc.
django.project(env.project_name)
from django.conf import settings as catalog_settings


@hosts('dev.commons.asu.edu')
@task
def docs(remote_path='/home/www/dev.commons.asu.edu/catalog/'):
    with lcd(env.docs_path):
        local("/usr/bin/make html")
        rsync_project(local_dir='build/html/', remote_dir=os.path.join(remote_path, 'apidocs'), delete=True)
    execute(coverage)
    rsync_project(local_dir='htmlcov/', remote_dir=os.path.join(remote_path, 'coverage'), delete=True)
    with cd(remote_path):
        sudo('find . -type d -exec chmod a+rx {} \; && chmod -R a+r .')


@task
def clean_update():
    local("git fetch --all && git reset --hard origin/master")


@task
def sh():
    dj('shell_plus')


def dj(command, **kwargs):
    """
    Run a Django manage.py command on the server.
    """
    _virtualenv(local,
                'python manage.py {dj_command} --settings {project_conf}'.format(dj_command=command, **env), **kwargs)


def _virtualenv(executor, *commands, **kwargs):
    """ source the virtualenv before executing this command """
    command = ' && '.join(commands)
    with prefix('. %(virtualenv_path)s/bin/activate' % env):
        executor(command, **kwargs)


@task
def host_type():
    run('uname -a')


@roles('localhost')
@task
def coverage():
    execute(test, coverage=True)
    ignored = ['*{0}*'.format(ignored_pkg) for ignored_pkg in env.ignored_coverage]
    local('coverage html --omit=' + ','.join(ignored))


@roles('localhost')
@task
def test(name=None, coverage=False):
    if name is not None:
        env.apps = name
    else:
        env.apps = ' '.join(catalog_settings.CATALOG_APPS)
    if coverage:
        ignored = ['*{0}*'.format(ignored_pkg) for ignored_pkg in env.ignored_coverage]
        env.python = "coverage run --source='.' --omit=" + ','.join(ignored)
    local('%(python)s manage.py test %(apps)s' % env)


@task
def server(ip="127.0.0.1", port=8000):
    dj('runserver {ip}:{port}'.format(ip=ip, port=port), capture=False)


@task
def dev():
    execute(staging)


@roles('staging')
@task
def staging():
    execute(deploy, 'develop')


@roles('prod')
@task
def prod(user=None):
    execute(deploy, 'master', user)


@roles('localhost')
@task
def setup_solr():
    _virtualenv(local, 'python manage.py build_solr_schema > %(abs_project_path)s/schema.xml' % env)
    sudo('cp %(abs_project_path)s/schema.xml %(solr_conf_dir)s/' % env)


@roles('localhost')
@task
def setup():
    execute(setup_postgres)
    execute(initialize_database_schema)
    execute(zotero_import)
    execute(setup_solr)
    execute(rebuild_index)


@task(alias='rfd')
def restore_from_dump(dumpfile='catalog.sql', init_db_schema=True):
    local('dropdb --if-exists %(db_name)s -U %(db_user)s' % env)
    local('createdb %(db_name)s -U %(db_user)s' % env)
    if os.path.isfile(dumpfile):
        logger.debug("loading data from %s", dumpfile)
        env.dumpfile = dumpfile
        local('psql %(db_name)s %(db_user)s < %(dumpfile)s' % env)
    if init_db_schema:
        execute(initialize_database_schema)


@task(aliases=['idb', 'init_db'])
def initialize_database_schema():
    local('python manage.py makemigrations')
    local('python manage.py migrate')


@task(alias='zi')
def zotero_import(group=None, collection=None):
    _command = 'python manage.py zotero_import'
    if group:
        _command += ' --group=%s' % group
    if collection:
        _command += ' --collection=%s' % collection
    local(_command)


@task(alias='ri')
def rebuild_index():
    local('python manage.py rebuild_index')


@roles('localhost')
@task
def setup_postgres():
    execute(createuser)
    execute(createdb)

@roles('localhost')
@task
def createuser():
    local("createuser %(db_user)s -rd -U postgres" % env)

@roles('localhost')
@task
def createdb():
    local("createdb %(db_name)s -U %(db_user)s" % env)


@task(alias='relu')
def reload_uwsgi():
    status_line = sudo("supervisorctl status | grep %(project_name)s" % env)
    m = re.search('RUNNING(?:\s+)pid\s(\d+)', status_line)
    if m:
        uwsgi_pid = m.group(1)
        logger.debug("sending HUP to %s", uwsgi_pid)
        sudo("kill -HUP {}".format(uwsgi_pid))
    else:
        logger.warning("No pid found: %s", status_line)


@roles('localhost')
@task
def clean():
    with cd(env.project_path):
        sudo('find . -name "*.pyc" -delete -print')
        sudo('rm -rvf htmlcov')
        sudo('rm -rvf docs/build')


def sudo_chain(*commands, **kwargs):
    sudo(' && '.join(commands), **kwargs)


def deploy(branch, user):
    """ deploy to an already setup environment """
    if user is None:
        user = env.deploy_user
    env.user = user
    env.deploy_dir = env.deploy_parent_dir + env.project_name
    env.branch = branch
    env.virtualenv_path = '/comses/virtualenvs/{}'.format(env.project_name)
    env.vcs_command = 'export GIT_WORK_TREE={} && git checkout -f {} && git pull'.format(env.deploy_dir, env.branch)
    if console.confirm("Deploying '%(branch)s' branch to host %(host)s : \n\r%(vcs_command)s\nContinue? " % env):
        with cd(env.deploy_dir):
            sudo_chain(
                env.vcs_command,
                user=user, pty=True)
            env.static_root = catalog_settings.STATIC_ROOT
            if console.confirm("Update pip dependencies?"):
                _virtualenv(sudo, 'pip install -Ur requirements.txt', user=user)
            if console.confirm("Run database migrations?"):
                _virtualenv(sudo, '%(python)s manage.py migrate' % env, user=user)
            _virtualenv(sudo, '%(python)s manage.py collectstatic' % env, user=user)
            sudo_chain(
                'chmod -R ug+rw .',
                'find %(static_root)s %(virtualenv_path)s -type d -exec chmod a+x {} \;' % env,
                'find %(static_root)s %(virtualenv_path)s -type f -exec chmod a+r {} \;' % env,
                'find . -type d -exec chmod ug+x {} \;',
                'chown -R %(deploy_user)s:%(deploy_group)s . %(static_root)s %(virtualenv_path)s' % env,
                pty=True)
            execute(reload_uwsgi)
