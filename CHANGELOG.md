# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [2.3.1](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v2.3.0...v2.3.1) (2026-01-22)

### 🐛 Bug Fixes

* pass session_file to collector and fix speedtest field name ([01c4d54](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/01c4d5489403b5178c86bbff80707df12555eebd))

## [2.3.0](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v2.2.3...v2.3.0) (2026-01-21)

### ✨ Features

* **ci:** add PyPI publishing to release workflow ([6ff1f2c](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/6ff1f2cb2131632dc80cdf1a8243a380b47682af))

### 🐛 Bug Fixes

* **deps:** pin eero-api to exact version ([b773b54](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/b773b54072e24ca7c65a4418da5fb96bc0fd82dd))

## [2.2.3](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v2.2.2...v2.2.3) (2026-01-20)

### 🐛 Bug Fixes

* **ci:** add prTitle config for squash merge commitlint compliance ([f148e73](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/f148e7336efa3cd7935b4caf5fe1235f9d2d38ac))

## [2.2.2](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v2.2.1...v2.2.2) (2026-01-20)

### 🐛 Bug Fixes

* **ci:** prevent commitlint body-max-line-length failures on Renovate PRs ([583e451](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/583e451aff7ef72741262b65012c051309816eba))

## [2.2.1](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v2.2.0...v2.2.1) (2026-01-20)

### 🐛 Bug Fixes

* **adapter:** convert upstream exceptions to local ones ([d0637bb](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/d0637bb76bac2b0f23da2b1951140febe6979876))

## [2.2.0](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v2.1.4...v2.2.0) (2026-01-19)

### ✨ Features

* trigger minor release ([1333ae5](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/1333ae5906d3a0daf99a07afb04ca13255a8d870))

## [2.1.4](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v2.1.3...v2.1.4) (2026-01-19)

### 🐛 Bug Fixes

* **ci:** remove invalid workflows permission from auto-merge ([5154bc8](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/5154bc814921b0a207e7ec24a8ba7502fe6d96dc))

## [2.1.3](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v2.1.2...v2.1.3) (2026-01-18)

### 🐛 Bug Fixes

* **ci:** use GitHub App for auto-merge to support workflow file changes ([bf1fe85](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/bf1fe851de6e7729e93f16b41693dcd180973887))

## [2.1.2](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v2.1.1...v2.1.2) (2026-01-18)

### 🐛 Bug Fixes

* **ci:** fix Renovate config validation errors ([a4fdc24](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/a4fdc240ab70b6b9486bbe3e4c4e1959e3fecfb8))

## [2.1.1](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v2.1.0...v2.1.1) (2026-01-18)

### 🐛 Bug Fixes

* **ci:** use head_ref for PR concurrency grouping ([7752ed5](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/7752ed53b373a1e30426da49c3fa6ecaa2c215f0))

## [2.1.0](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v2.0.0...v2.1.0) (2026-01-17)

### ✨ Features

* **security:** migrate from Bandit to Semgrep ([7ea08a6](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/7ea08a672ec65184f69319f2c49116a6c59482d2))

## [2.0.0](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v1.1.2...v2.0.0) (2026-01-17)

### ⚠ BREAKING CHANGES

* Python 3.10 and 3.11 are no longer supported

- Update requires-python to >=3.12
- Update classifiers to 3.12, 3.13, 3.14
- Update mypy python_version to 3.12
- Update ruff target-version to py312
- Update CI test matrix to 3.12, 3.13, 3.14
- Update README badge and requirements

### ✨ Features

* require Python 3.12 minimum ([736e07b](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/736e07bd6b0beadaa463a9d2ef59240f2b0274f8))

### 🐛 Bug Fixes

* **ci:** require ALL jobs to pass for CI Success ([b7a7d07](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/b7a7d07412c44aa36ebf0e603bf18fe569bf0a8a))
* replace asyncio.TimeoutError with built-in TimeoutError ([88ee0f1](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/88ee0f1b923cc3927f62d63619d92e7ae4e3fda2))
* resolve lint, format, and type-check CI failures ([7f1b68a](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/7f1b68afc8c61b1d83c399614d6b0c5edfa3e7aa))
* suppress bandit B104 security warnings for intentional 0.0.0.0 binding ([18504de](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/18504de9b43c3266d357b2fed82186cb63f16a9a))

### ♻️ Refactoring

* update repository_dispatch event type name ([d74fe03](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/d74fe0372d2d8886359fd5afc1255df5ad09073f))

## [1.1.2](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v1.1.1...v1.1.2) (2026-01-17)

### 🐛 Bug Fixes

* **ci:** properly report type-check and security job status ([8c7f34c](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/8c7f34cbb2a26a8467345301b1edc1d80495c350))

## [1.1.1](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v1.1.0...v1.1.1) (2026-01-17)

### 🐛 Bug Fixes

* **ci:** remove dead repository_dispatch code from CI workflow ([f1cb82d](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/f1cb82dff31f5f9d770ad3971fca648b798aadb2))

## [1.1.0](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v1.0.1...v1.1.0) (2026-01-17)

### ✨ Features

* **ci:** migrate workflows to use reusable actions from eero-client ([9b19b33](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/9b19b33b27bf77305e8e74175334bc037273c9f8))

### 🐛 Bug Fixes

* **ci:** use master branch consistently in all workflows ([0167833](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/016783363160d4286957b0978728bca8d78ee428))
* **ci:** use master branch only in triggers ([f152d71](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/f152d71f788539e49fc0abc78396c1a20b64a6e0))

### ♻️ Refactoring

* **ci:** standardize pipeline chain format ([ab4d473](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/ab4d4737dfc240232ac570e5747c1584b43aaa82))

## [1.0.1](https://github.com/fulviofreitas/eero-prometheus-exporter/compare/v1.0.0...v1.0.1) (2026-01-16)

### 🐛 Bug Fixes

* **release:** prevent sed from modifying tool config versions ([e13afce](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/e13afced29b6b5bce6a91292afc13861a339c579))

## 1.0.0 (2026-01-16)

### ✨ Features

* add comprehensive wireless and hardware metrics ([90a4c0b](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/90a4c0bbe51065bfd65b97670dbf8c368295c0b9))
* **ci:** add Renovate for eero-client dependency tracking ([3196156](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/3196156db828a8793ad700646fdc9dbfdb3f7704))
* **grafana:** add auto-provisioning for datasource and dashboard ([d28f792](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/d28f792766f4cd45ff6894ef717a9c942f367c30))
* **grafana:** improve dashboard panels and fix data issues ([103e77c](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/103e77ccaf5297efc1b13078eb049bfa9d92527b))
* **metrics:** enrich device metrics with additional labels ([cec58a7](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/cec58a7daec6e58a7e6b3fa042e452ddd9ff0d1a))

### 🐛 Bug Fixes

* **ci:** resolve lint errors and handle missing tests ([2c3a6d2](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/2c3a6d2f375fe9be6a831c9d4b0e6fefd94e520f))
* correct eero-client exception names and auth flow ([a9380f5](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/a9380f54517cdf05f30d34caef2dca4ad296940d))
* **grafana:** filter out wired devices (0 dBm) from signal strength graph ([dca7d0b](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/dca7d0b2dcc6e54505b52e4e0063911a7756f09c))
* install git in Docker for eero-client dependency ([72f656a](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/72f656a4b50094105fd20bab40454801417664de))
* properly serialize Pydantic enums to string values ([6631d53](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/6631d537be9edcfcbf90efcd6bdd925af0b4231f))

### ♻️ Refactoring

* use eero-client library as official API client ([c562b8f](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/c562b8f2fc08b6a2deed79405e24312f6f4b95f2))

### 📚 Documentation

* add Docker setup instructions ([2c01e34](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/2c01e34147910c3d31a6e516a78c73d322c32b26))
* clarify eero-client is unofficial API client ([9bb9f9e](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/9bb9f9eed3dc7c5326f255f25ddc69dd98a1de78))
* update documentation with 90+ metrics reference ([6618fe7](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/6618fe73858ad4f328915bbdeb3e4f1619bf6d4d))
* update README and simplify session file usage ([c0c8438](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/c0c8438a15f6e454bfdda765f4a4723f1b4fef77))
* update README for eero-client integration ([4215e11](https://github.com/fulviofreitas/eero-prometheus-exporter/commit/4215e118c955977a9a6431c8a361fc8c771957e2))
