Name:           demo
Version:        1.0.0
Release:        1%{?dist}
Summary:        Policy stage demo package
License:        MIT
URL:            https://example.com/demo

%description
Demo package for gorget's Policy stage -- vendors a real npm dependency and
confirms it meets a declared minimum version.

%prep

%build

%install

%files

%changelog
* Mon Jan 01 2024 Demo <demo@example.com> - 1.0.0-1
- Initial
