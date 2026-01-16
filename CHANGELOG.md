# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


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
