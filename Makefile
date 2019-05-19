
all:
	@vagrant up
	@vagrant ssh molior -- molior/vagrant/build.sh
	@echo Login to the molior LXC container: make vssh
	@echo

destroy:
	@vagrant destroy -f

vssh:
	@vagrant ssh molior || true

halt:
	@vagrant halt

.PHONY: all destroy vssh halt
