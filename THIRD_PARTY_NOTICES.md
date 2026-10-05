# Third-party notices

## HBCI4Java

The internal read-only FinTS gateway uses
[`com.github.hbci4j:hbci4j-core`](https://github.com/hbci4j/hbci4java), version
4.1.12, without source modifications, for bank discovery, account discovery,
balances and transactions. HBCI4Java is distributed under the GNU Lesser
General Public License, version 2.1. Its packaged bank directory is used through
the library API and is not copied into the Finsight source tree.

The FinTS bank-directory redistribution terms remain subject to upstream
clarification before Finsight publishes prebuilt gateway images. Source builds
resolve the version-pinned official Maven artifact directly and make Maven fail
the build when repository checksums do not match.

The repository's [MIT license](LICENSE) covers finsight's own code. Dependencies
and third-party assets retain their respective licenses and trademark rights.

## Dependencies

[`python-mnemonic`](https://github.com/trezor/python-mnemonic), used only to
generate and validate the BIP-39 recovery phrase, is distributed under the
**MIT License**, copyright (c) 2013-2016 Pavol Rusnak. Its wheel is likewise
pinned by URL and SHA-256 in `backend/requirements.txt`; the upstream notice is
reproduced in [`docs/licenses/python-mnemonic-MIT.txt`](docs/licenses/python-mnemonic-MIT.txt).
Other Python and JavaScript packages retain their package licenses. This page
is not a complete dependency license inventory.

The frontend bundles **Chakra Petch** and **Source Sans 3** through Fontsource.
Both typefaces are distributed under the SIL Open Font License 1.1; no font CDN
is contacted at runtime.

## Trade Republic protocol research

The read-only Trade Republic adapter in
`backend/app/adapters/traderepublic.py` is an independent integration for
finsight's data model and encrypted storage. It does not bundle or import a
Trade Republic client library at runtime. Its understanding of Trade Republic's
undocumented login flow, WebSocket protocol, endpoints and response structures
was informed by the [`pytr`](https://github.com/pytr-org/pytr) project.

`pytr` is licensed under the **MIT License**, copyright (c) 2020 marzzzello.
The upstream copyright and permission notice are reproduced in
[`docs/licenses/pytr-MIT.txt`](docs/licenses/pytr-MIT.txt). This attribution does
not imply that `pytr` or its contributors endorse finsight.

## Provider icons

These icons identify connected data sources. They do not imply a partnership,
endorsement or approval by their owners.

- **Volksbank:** `frontend/public/brands/volksbank.svg` adapts BVR's
  [Volksbank logo](https://commons.wikimedia.org/wiki/File:Volksbank_Logo.svg),
  licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
  Paths were cleaned and colors adjusted. The asset remains under that license;
  see [attribution](frontend/public/brands/README.md).
- **Trade Republic:** the icon in `frontend/src/lib/icons.tsx` is based on the
  [2021 logo geometry](https://commons.wikimedia.org/wiki/File:Trade_Republic_logo_2021.svg).
  Commons describes it as simple geometric artwork; trademark rights still apply.
- **Binance:** the icon path in `frontend/src/lib/icons.tsx` comes from
  [Simple Icons](https://github.com/simple-icons/simple-icons), whose icon files
  use CC0 1.0. The Binance name and mark retain their trademark protection.
- **Coinbase:** `frontend/public/brands/coinbase.svg` crops the unchanged blue
  `C` glyph from Coinbase's
  [official press logo pack](https://www.coinbase.com/press). Coinbase's brand
  guidelines and trademark rights apply.
- **Trading 212:** `frontend/public/brands/trading212.svg` is based on the
  [Trading 212 SVG](https://www.svgrepo.com/svg/331610/trading-212) whose source
  page marks that asset as CC0. Trading 212's name and mark remain protected
  trademarks.
- **Sparkasse, Deutsche Bank, Commerzbank and N26:** the local SVG path
  geometries come from
  [Simple Icons 16.34.0](https://github.com/simple-icons/simple-icons/tree/16.34.0)
  and retain their respective trademark protection. Their individual upstream
  artwork sources and colors are recorded in
  [`frontend/public/brands/README.md`](frontend/public/brands/README.md).
- **Other bank names:** Finsight currently renders a neutral initials badge,
  not the bank's artwork. The official source and the reason no logo is bundled
  are recorded in [`frontend/public/brands/README.md`](frontend/public/brands/README.md).

## Wordmark

The README wordmark uses outlines from **Chakra Petch Bold**, by Cadson Demak,
the same typeface used by the application. Font source:
[Google Fonts](https://github.com/google/fonts/tree/main/ofl/chakrapetch),
licensed under the [SIL Open Font License 1.1](docs/assets/ChakraPetch-OFL.txt).
