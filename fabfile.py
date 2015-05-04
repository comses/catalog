from fabric.api import local, sudo, cd, env, lcd, execute, hosts, roles, task, run
from fabric.context_managers import prefix
from fabric.contrib.console import confirm
from fabric.contrib import django
from fabric.contrib.project import rsync_project
import sys
import os
import logging

logger = logging.getLogger(__name__)

# default to current working directory
env.project_path = os.path.dirname(__file__)
# needed to push catalog.settings onto the path.
env.abs_project_path = os.path.abspath(env.project_path)
sys.path.append(env.abs_project_path)

# default env configuration
env.roledefs = {
    'localhost': ['localhost'],
    'staging': ['dev.catalog.comses.net'],
    'prod': ['catalog.comses.net'],
}
env.python = 'python'
env.project_name = 'catalog'
env.project_conf = 'catalog.settings'
env.deploy_user = 'catalog'
env.deploy_group = 'catalog'
env.database = 'default'
env.deploy_parent_dir = '/opt/'
env.git_url = 'https://github.com/comses/catalog.git'
env.services = 'nginx memcached redis supervisord'
env.docs_path = os.path.join(env.project_path, 'docs')
env.virtualenv_path = '%s/.virtualenvs/%s' % (os.getenv('HOME'), env.project_name)
env.ignored_coverage = ('test', 'settings', 'migrations', 'fabfile', 'wsgi', 'management')
env.solr_conf_dir = '/etc/solr/conf'
env.db_user = 'catalog'
env.db_name = 'comses_catalog'
env.vcs = 'git'
env.vcs_command = 'export GIT_WORK_TREE=%(deploy_dir)s && git checkout -f %(branch)s && git pull'

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
def migrate():
    local("%(python)s manage.py migrate" % env, capture=False)


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
def prod():
    execute(deploy, 'master')


@roles('localhost')
@task
def setup_solr():
    _virtualenv(local, 'python manage.py build_solr_schema > %(abs_project_path)s/schema.xml' % env)
    sudo('cp %(abs_project_path)s/schema.xml %(solr_conf_dir)s/' % env)
    execute(restart_solr)


@task
def restart_solr():
    # FIXME: for RHEL, systemctl restart solr or service solr restart, need to switch on os type?
    sudo('service tomcat6 restart')


@roles('localhost')
@task
def setup():
    execute(setup_postgres)
    execute(initialize_database_schema)
    execute(zotero_import)
    execute(setup_solr)
    execute(rebuild_index)

@task
def init_db():
    execute(initialize_database_schema)


@task
def initialize_database_schema():
    local('python manage.py makemigrations')
    local('python manage.py migrate')


@task
def zotero_import():
    local('python manage.py zotero_import')


@roles('localhost')
@task
def rebuild_index():
    local('python manage.py rebuild_index')

@task
def ri():
    execute(rebuild_index)


@roles('localhost')
@task
def setup_postgres():
    local("psql -c 'create user %(db_user)s CREATEDB' -U postgres" % env)
    local("psql -c 'create database %(db_name)s OWNER=%(db_user)s' -U postgres" % env)


def _restart_command(systemd=True):
    """
    FIXME: look into less drastic ways to reload the app and sockjs servers
    """
    if systemd:
        cmd = 'systemctl restart %(services)s && systemctl status -l %(services)s'
    else:
        cmd = ' && '.join(['service %s restart' % service for service in env.services.split()])
    return cmd % env


@roles('localhost')
@task
def clean():
    with cd(env.project_path):
        sudo('find . -name "*.pyc" -delete -print')
        sudo('rm -rvf htmlcov')
        sudo('rm -rvf docs/build')


@task
def restart():
    sudo(_restart_command(), pty=True)


def sudo_chain(*commands, **kwargs):
    sudo(' && '.join(commands), **kwargs)


def deploy(branch):
    """ deploy to an already setup environment """
    env.deploy_dir = env.deploy_parent_dir + env.project_name
    env.branch = branch
    if confirm("Deploying '%(branch)s' branch to host %(host)s : \n\r%(vcs_command)s\nContinue? " % env):
        with cd(env.deploy_dir):
            sudo_chain(
                env.vcs_command,
                'chmod g+s logs',
                'chmod -R g+rw logs/',
                user=env.deploy_user, pty=True)
            env.static_root = catalog_settings.STATIC_ROOT
            if confirm("Update pip dependencies?"):
                _virtualenv(sudo, 'pip install -Ur requirements.txt', user=env.deploy_user)
            if confirm("Run database migrations?"):
                _virtualenv(sudo, '%(python)s manage.py migrate' % env, user=env.deploy_user)
            _virtualenv(sudo, '%(python)s manage.py collectstatic' % env)
            sudo_chain(
                'chmod -R ug+rw .',
                'find %(static_root)s %(virtualenv_path)s -type d -exec chmod a+x {} \;' % env,
                'find %(static_root)s %(virtualenv_path)s -type f -exec chmod a+r {} \;' % env,
                'find . -type d -exec chmod ug+x {} \;',
                'chown -R %(deploy_user)s:%(deploy_group)s . %(static_root)s %(virtualenv_path)s' % env,
                _restart_command(),
                pty=True)
