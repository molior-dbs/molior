#!/bin/sh

set -e

# timezone
rm -f /etc/localtime
ln -s /usr/share/zoneinfo/Europe/Zurich /etc/localtime
echo "Europe/Zurich" > /etc/timezone

# vim
sed -i 's/"syntax on/syntax on/' /etc/vim/vimrc
sed -i 's/"set background=dark/set background=dark/' /etc/vim/vimrc

# psql
mkdir -p /var/lib/postgresql/
echo '\pset pager off' > /var/lib/postgresql/.psqlrc


# user configuration
SYSUSER=vagrant
SYSHOME=/home/vagrant
cat >>$SYSHOME/.bash_aliases <<EOF
alias log='sudo journalctl -f'
build() { ~/molior/vagrant/build.sh \$@; }
alias resize='sudo resize2fs /dev/vda1'
alias rm='rm -i'
alias mv='mv -i'
alias cp='cp -i'
alias grep='grep -Is --exclude=.git --color=auto'

setup_vim()
{
    dir=$PWD
    git clone https://github.com/timofurrer/.vim ~/.vim
    cd ~/.vim
    git submodule update --init --recursive
    cd pack/programming/start/YouCompleteMe
    python3 install.py --clang-completer
    cd $dir
}
EOF

cp /etc/skel/.bashrc /etc/skel/.profile $SYSHOME/
sed -i 's/^#force_color_prompt=yes$/force_color_prompt=yes/' $SYSHOME/.bashrc

cat >> $SYSHOME/.bashrc << EOF

if [ ! -f ~/.resized ]; then
  touch ~/.resized
  sudo resize2fs /dev/vda1
fi

IP=\`/sbin/ifconfig eth0 | grep "inet " | awk '{print \$2}'\`
echo
echo -e "===> To build molior type build"
echo -e "===> To watch the logs type log"
if [ ! -d ~/.vim ]; then
  echo -e "===> To configure vim type setup_vim"
fi
echo "===> WebUI: http://\$IP/"
echo
EOF

chown vagrant.vagrant /home/vagrant/.bashrc $SYSHOME/.bash_aliases

sed -i "s/^#force_color_prompt=yes/force_color_prompt=yes/" $SYSHOME/.bashrc
sed -i 's/#export GCC_COLORS=/export GCC_COLORS=/' $SYSHOME/.bashrc
if ! grep -q __git_ps1 $SYSHOME/.bashrc; then
    sed -i "s/\\\\\$ '$/\$(__git_ps1)\\\\\$ '/" $SYSHOME/.bashrc
fi

su $SYSUSER -c "git config --global color.diff auto"
su $SYSUSER -c "git config --global color.status auto"
su $SYSUSER -c "git config --global color.branch auto"
su $SYSUSER -c "git config --global color.grep auto"
su $SYSUSER -c "git config --global alias.st status"
su $SYSUSER -c "git config --global alias.co checkout"
su $SYSUSER -c "git config --global alias.ci commit"
su $SYSUSER -c "git config --global alias.br branch"
su $SYSUSER -c "git config --global push.default simple"

cat >$SYSHOME/.vimrc <<EOF
set mouse=
if filereadable(glob("~/.vim/vimrc"))
    source ~/.vim/vimrc
endif
EOF
cp $SYSHOME/.vimrc /root

# install shared SSH key
cp -ar /vagrant//vagrant/sshkeys/* /home/vagrant/.ssh/
chown vagrant:vagrant /home/vagrant/.ssh/*

# make sure hostname is registered in DNS
ifdown eth0 2>/dev/null
ifup eth0 2>/dev/null

echo "Provisioning done!"
echo 'Login to molior: vagrant ssh molior'
