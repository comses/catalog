# -*- mode: ruby -*-
# vi: set ft=ruby :

# All Vagrant configuration is done below. The "2" in Vagrant.configure
# configures the configuration version (we support older styles for
# backwards compatibility). Please don't change it unless you know what
# you're doing.
Vagrant.configure(2) do |config|
	# The most common configuration options are documented and commented below.
	# For a complete reference, please see the online documentation at
	# https://docs.vagrantup.com.

	# Every Vagrant development environment requires a box. You can search for
	# boxes at https://atlas.hashicorp.com/search.
	config.vm.box = "ubuntu/xenial64"

	# Disable automatic box update checking. If you disable this, then
	# boxes will only be checked for updates when the user runs
	# `vagrant box outdated`. This is not recommended.
	# config.vm.box_check_update = false

	# Create a forwarded port mapping which allows access to a specific port
	# within the machine from a port on the host machine. In the example below,
	# accessing "localhost:8080" will access port 80 on the guest machine.

	# solr
	config.vm.network "forwarded_port", guest: 8983, host: 8983

	# django
	config.vm.network "forwarded_port", guest: 8000, host: 8000

	# postgresql
	config.vm.network "forwarded_port", guest: 5432, host: 5432

	# Create a private network, which allows host-only access to the machine
	# using a specific IP.
	# config.vm.network "private_network", ip: "192.168.33.10"

	# Create a public network, which generally matched to bridged network.
	# Bridged networks make the machine appear as another physical device on
	# your network.
	# config.vm.network "public_network"

	# Share an additional folder to the guest VM. The first argument is
	# the path on the host to the actual folder. The second argument is
	# the path on the guest to mount the folder. And the optional third
	# argument is a set of non-required options.
	config.vm.synced_folder ".", "/vagrant"

	# Provider-specific configuration so you can fine-tune various
	# backing providers for Vagrant. These expose provider-specific options.
	# Example for VirtualBox:
	#
	config.vm.provider "virtualbox" do |vb|
	#   # Display the VirtualBox GUI when booting the machine
	#   vb.gui = true
	#
	# Customize the amount of memory on the VM:
		vb.memory = "4096"
	end
	#
	# View the documentation for the provider you are using for more
	# information on available options.

	# Define a Vagrant Push strategy for pushing to Atlas. Other push strategies
	# such as FTP and Heroku are also available. See the documentation at
	# https://docs.vagrantup.com/v2/push/atlas.html for more information.
	# config.push.define "atlas" do |push|
	#   push.app = "YOUR_ATLAS_USERNAME/YOUR_APPLICATION_NAME"
	# end

	# Enable provisioning with a shell script. Additional provisioners such as
	# Puppet, Chef, Ansible, Salt, and Docker are also available. Please see the
	# documentation for more information about their specific syntax and use.
	config.vm.provision "shell", inline: <<-SHELL
		sudo apt-get update
		sudo apt-get install -y postgresql postgresql-client-common postgresql-server-dev-9.5 \
		solr-tomcat git \
		libxml2 libxml2-dev \
		libxslt1.1 libxslt1-dev \
		python3-pip python3-dev python-libxml2 python-libxslt1 python-pip

		HOME=/home/ubuntu
		BASEDIR=/vagrant
		SETTINGSDIR=${BASEDIR}/catalog/settings

		SOLR_VERSION="4.10.4"

		echo "BASEDIR $BASEDIR"
		echo "SETTINGSDIR $SETTINGSDIR"

		prepare_python() {
			sudo pip3 install virtualenv
			sudo pip install fabric
			mkdir -p $HOME/.virtualenvs
			virtualenv $HOME/.virtualenvs/catalog
			. $HOME/.virtualenvs/catalog/bin/activate

			cd $BASEDIR
			pip install -Ur requirements.txt
			deactivate
		}
		prepare_python

		install_java() {
			cd /opt
			sudo wget --cookies --no-check-certificate --header \
				"Cookie: gpw_e24=http%3A%2F%2Fwww.oracle.com%2F; oraclelicense=accept-securebackup-cookie" \
				"http://download.oracle.com/otn-pub/java/jdk/8u77-b03/jdk-8u77-linux-x64.tar.gz"
			sudo tar xzf jdk-8u77-linux-x64.tar.gz
			sudo rm -rf jdk-8u77-linux-x64.tar.gz
			cd -
		}
		install_java

		# Replace postgres settings file
		cp $BASEDIR/deploy/vagrant/pg_hba.conf "/etc/postgresql/9.5/main/pg_hba.conf"
		sudo service postgresql restart

		# Create a local settings file
		cp $SETTINGSDIR/local.py.example $SETTINGSDIR/local.py

		install_solr() {
			SOLR_TGZ="solr-${SOLR_VERSION}.tgz"
			if [ ! -f $SOLR_TGZ ]; then
				wget http://archive.apache.org/dist/lucene/solr/${SOLR_VERSION}/solr-${SOLR_VERSION}.tgz
			fi
			if [ -f $SOLR_TGZ ]; then
				tar xzf solr-${SOLR_VERSION}.tgz
			else
				echo "$SOLR_TGZ does not exist"
				exit 1
			fi
		}
		install_solr

		. $HOME/.virtualenvs/catalog/bin/activate
		invoke setup_postgres
		invoke initialize_database_schema
	SHELL
end
