# -*- mode: ruby -*-
# vi: set ft=ruby :

require 'etc'

if ARGV[0] == "up"
  # early ask for sudo password
  system( 'sudo true' )
  # prepare SSH keys
  vagrant_root = File.dirname(__FILE__)
  system( "#{vagrant_root}/vagrant/create-keys.sh" )
end


required_plugins = %w( vagrant-timezone vagrant-lxc )
required_plugins.each do |plugin|
      exec "vagrant plugin install #{plugin};vagrant #{ARGV.join(" ")}" unless Vagrant.has_plugin? plugin || ARGV[0] == 'plugin'
end

ENV['VAGRANT_DEFAULT_PROVIDER'] = 'lxc'
ENV['VAGRANT_NO_PARALLEL'] = 'yes'

# get user id and group
login = Etc.getlogin
info = Etc.getpwnam(login)
user_id = info.uid
group_id = info.gid

# All Vagrant configuration is done below. The "2" in Vagrant.configure
# configures the configuration version (we support older styles for
# backwards compatibility). Please don't change it unless you know what
# you're doing.
Vagrant.configure(2) do |config|
  # Set the timezone to the host timezone
  if Vagrant.has_plugin?("vagrant-timezone")
    config.timezone.value = :host
  end

  config.vm.provider "lxc"
  config.vm.box = "debian/stretch64"

  # dns configuration using landrush [DOES NOT WORK ;(]
  #config.landrush.enabled = true
  #config.landrush.tld = '.devel'
  #config.landrush.host_interface = 'eth0'
  #config.landrush.guest_redirect_dns = false
  #config.landrush.host_interface_excludes = [/lo[0-9]*/, /docker[0-9]+/, /vnet[0-9]+/ ]

  # Prevent TTY Errors
  config.ssh.shell = "bash -c 'BASH_ENV=/etc/profile exec bash'"

  config.vm.define "node", autostart: true do |buildnode|
      buildnode.vm.hostname = "node1.devel"
      buildnode.vm.provider :lxc do |lxc|
          lxc.backingstore = 'dir'
      end

      # install and configure the VM
      buildnode.vm.provision :shell, path:"vagrant/node-install.sh"
      buildnode.vm.provision :shell, path:"vagrant/node-configure.sh"
  end

  config.vm.define "molior", autostart: true do |molior|
      molior.vm.hostname = "molior.devel"
      molior.vm.provider :lxc do |lxc|
          lxc.backingstore = 'dir'
      end

      # install and configure the VM
      molior.vm.provision :shell, path:"vagrant/install.sh"
      molior.vm.provision :shell, path:"vagrant/configure.sh"
      molior.vm.provision :shell, path:"vagrant/change-ids.sh", args: "#{user_id} #{group_id}" # must be last

      molior.vm.synced_folder "../molior", "/home/vagrant/molior"
      molior.vm.synced_folder "../molior-web", "/home/vagrant/molior-web"
      molior.vm.synced_folder "../molior", "/home/vagrant/molior"
      molior.vm.synced_folder "../aptlydeb", "/home/vagrant/aptlydeb"
      molior.vm.synced_folder "../cirrina", "/home/vagrant/cirrina"
      molior.vm.synced_folder "../launchy", "/home/vagrant/launchy"
      molior.vm.synced_folder "../aiohttp_jrpc", "/home/vagrant/aiohttp_jrpc"
      molior.vm.synced_folder "../aiohttp-session", "/home/vagrant/aiohttp-session"
      molior.vm.synced_folder "../aiohttp-swagger", "/home/vagrant/aiohttp-swagger"
  end
end
