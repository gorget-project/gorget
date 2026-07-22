Name:           multisource
Version:        2.3.4
Release:        1%{?dist}
Summary:        A test package with multiple sources
License:        MIT
URL:            https://example.com/%{name}
Source0:        https://example.com/%{name}/%{name}-%{version}.tar.gz
Source1:        https://example.com/%{name}/extra-data.tar.gz
Source2:        %{url}/patches.tar.gz
Source3:        https://example.com/%{name}/vendor-%{version}.tar.gz

%description
A test package with several Source declarations, including macro-based URLs.

%prep
%setup -q

%build

%install

%files

%changelog
* Mon Jan 01 2024 Test <test@example.com> - 2.3.4-1
- Initial package
