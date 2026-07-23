Name:           hello
Version:        2.12.1
Release:        1%{?dist}
Summary:        The "Hello, World!" program from GNU
License:        GPLv3+
URL:            https://www.gnu.org/software/hello/
Source0:        https://ftp.gnu.org/gnu/hello/hello-%{version}.tar.gz

%description
The GNU Hello program prints "Hello, world!" -- the traditional example used
in virtually every RPM packaging tutorial.

%prep
%setup -q

%build

%install

%files

%changelog
* Mon Jan 01 2024 Demo <demo@example.com> - 2.12.1-1
- Initial
