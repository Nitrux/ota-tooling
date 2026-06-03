# Nitrux Update Tool System OTA Build | [![License](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)

<p align="center">
  <img width="128" height="128" src="https://raw.githubusercontent.com/Nitrux/luv-icon-theme/master/Luv/apps/64/nx-software-updater.svg">
</p>

Nitrux Update Tool System OTA Build is a utility that creates OTA archives (SquashFS archives) for the [Nitrux Update Tool System](https://github.com/Nitrux/nuts-cpp) using package lists and package database archives generated during the build process of the Nitrux ISO files.

> [!WARNING]
> We intended the Nitrux Update Tool System to work exclusively in Nitrux OS; using the archives this utility creates in other distributions will break them or render them unusable. Please do not open issues regarding this use case; they will be closed.

# Usage

### Commands:

**Compare**: `ota-build compare`
- Compares two package lists and write the result lists.

**Download**: `ota-build download`
- Download packages from a list.

**Create**: `ota-build create`
- Create an OTA-style SquashFS archive.
  -  `create` writes the SquashFS archive plus `.contents` and `.md5sum` files next to it.

### Options:

```sh
--output-dir:
    where compare/download outputs are written.
--var-db-old / --var-db-new:
    use tarballs for better package transition detection.
```

# Licensing

The license for this repository and its contents is **BSD-3-Clause**.

# Issues

If you find problems with the contents of this repository, please create an issue and use the **🐞 Bug report** template.

## Submitting a bug report

Before submitting a bug, you should look at the [existing bug reports](https://github.com/Nitrux/ota-tooling/issues) to verify that no one has reported the bug already.

©2026 Nitrux Latinoamericana S.C.
