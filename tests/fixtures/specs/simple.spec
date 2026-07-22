Name:           simple
Version:        1.0.0
Release:        1%{?dist}
Summary:        A simple test package
License:        MIT
URL:            https://example.com/simple
Source0:        https://example.com/simple/simple-1.0.0.tar.gz

%description
A simple test package with a single plain Source URL.

%prep
%setup -q

%build

%install

%files

%changelog
* Mon Jan 01 2024 Test <test@example.com> - 1.0.0-1
- Initial package
