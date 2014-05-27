#! /bin/sh

debian_dist=wheezy
git_repo="https://github.com/pbrook/lhs-marvin.git"

echo "Adding backports repository"
# Enable backports directory
cat > /etc/apt/sources.list.d/backports.list << EOF
deb http://ftp.uk.debian.org/debian/ $debian_dist-backports main
deb-src http://ftp.uk.debian.org/debian/ $debian_dist-backports main
EOF
apt-get update

echo "Installing ansible and apt dependencies"
apt-get -y install ansible python-apt aptitude git

echo "checking out git repo"
git clone $git_repo marvin

echo "Done"
