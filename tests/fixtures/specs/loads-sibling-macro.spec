%{load:%{_sourcedir}/loads-sibling-macro.macros}

Name:           loads-sibling-macro
Version:        %{sibling_version}
Release:        1%{?dist}
Summary:        A test package whose spec loads a sibling macro file
License:        MIT
URL:            https://example.com/loads-sibling-macro
Source0:        https://example.com/loads-sibling-macro/loads-sibling-macro-%{version}.tar.gz

%description
Exercises SpecFile's sourcedir override: the macro file this spec loads via
%%{load:...} only exists next to the real package directory, not next to
whatever scratch copy of the spec gorget is validating.

%prep
%setup -q

%build

%install

%files

%changelog
* Mon Jan 01 2024 Test <test@example.com> - 1.0.0-1
- Initial package
