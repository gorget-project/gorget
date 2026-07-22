Name:           conditional
Version:        3.1.0
Release:        1%{?dist}
Summary:        A test package with conditional sources
License:        MIT
URL:            https://example.com/%{name}

%bcond_without bundled

Source0:        https://example.com/%{name}/%{name}-%{version}.tar.gz
%if %{with bundled}
Source1:        https://example.com/%{name}/bundled-deps.tar.gz
%endif

%description
A test package whose Source1 is only present when the "bundled" bcond is enabled.

%prep
%setup -q

%build

%install

%files

%changelog
* Mon Jan 01 2024 Test <test@example.com> - 3.1.0-1
- Initial package
