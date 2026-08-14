Name:           demo
Version:        1.0.0
Release:        1%{?dist}
Summary:        Demo package for gorget's minimal native git+vendor pipeline
License:        MIT
URL:            https://example.com

# Bare filenames, not download URLs: there's no upstream tarball to point at
# in the first place, gorget is what produces these two files (see this
# example's README and demo.source-pipeline.yaml).
Source0:        demo-%{version}.tar.gz
Source1:        demo-%{version}-vendor.tar.xz

%description
Demo package used to exercise gorget's minimal native-package Fetch pipeline
(fetch: git + fetch: vendor, ecosystem: cargo) -- no spec-source, no verify,
no transform, nothing else.

%prep
# -n must match the *archive's* internal top-level directory, which gorget's
# git step derives from archive_name (here "demo-%{version}.tar.gz" minus its
# suffix, i.e. "demo-1.0.0") -- not demo-repo/'s own directory name, and not
# necessarily Cargo.toml's [package].name either, if either of those ever
# diverges from the spec's %{name}. Get this wrong (e.g. a leftover
# "DemoRepo-%{version}" copied from some other spec) and %prep fails with
# "no such file or directory" even though the tarball fetched and archived
# fine.
%autosetup -n %{name}-%{version}
tar xf %{SOURCE1}

%build

%install

%files

%changelog
* Mon Jan 01 2024 Demo <demo@example.com> - 1.0.0-1
- Initial
