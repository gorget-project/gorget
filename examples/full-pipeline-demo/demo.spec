Name:           demo
Version:        1.0.0
Release:        1%{?dist}
Summary:        Demo package exercising every gorget pipeline primitive
License:        MIT
URL:            https://example.com

%description
Demo package used to exercise every stage of gorget's pipeline together:
Fetch, Transform, Verify, and Policy.

%prep
%build
%install
%files
%changelog
* Mon Jan 01 2024 Demo <demo@example.com> - 1.0.0-1
- Initial
