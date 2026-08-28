# Changelog

## [0.28.1](https://github.com/CubelliJ/harness/compare/v0.28.0...v0.28.1) (2026-08-28)


### Bug Fixes

* prevent replayed voice transcript text ([91212ab](https://github.com/CubelliJ/harness/commit/91212abb5b5a77e0d99e8eb79cd9342210db4440))


### Documentation

* add module decomposition plan ([88d5179](https://github.com/CubelliJ/harness/commit/88d5179a9cb6c8013ac81be3d577ccc67572c7d0))
* record cleanup and agent coverage ([14471c8](https://github.com/CubelliJ/harness/commit/14471c82d2ee5181aa9b91238c57812fdb1cede7))
* record CLI confirmation extraction ([324a18b](https://github.com/CubelliJ/harness/commit/324a18b5abfc5bc859600ff34d8bbef0f4117c34))
* record REPL extraction ([40b28f7](https://github.com/CubelliJ/harness/commit/40b28f776f8eb942a0ce09df3e0b307224b27b35))
* record terminal input extraction ([08f36e3](https://github.com/CubelliJ/harness/commit/08f36e372ee6fa214040d11813274623faed8e58))
* record tools package split ([0ec2a02](https://github.com/CubelliJ/harness/commit/0ec2a02ef1990760e102406cf1522256aaf71eca))
* record voice UI extraction ([cad42d6](https://github.com/CubelliJ/harness/commit/cad42d65c9b3d4825fbe7b72fc148b2907feb2b9))

## [0.28.0](https://github.com/CubelliJ/harness/compare/v0.27.0...v0.28.0) (2026-08-28)


### Features

* stream responses and render markdown incrementally ([f053dce](https://github.com/CubelliJ/harness/commit/f053dceb9d7dc60e0c1671289c7c6d82f541a6b9))

## [0.27.0](https://github.com/CubelliJ/harness/compare/v0.26.0...v0.27.0) (2026-08-28)


### Features

* add text search to the /model command ([dcc2adc](https://github.com/CubelliJ/harness/commit/dcc2adcb391464dac5a239502df8f656d2b9b856))
* allow saving a workspace default model from /model ([4450c55](https://github.com/CubelliJ/harness/commit/4450c55534538606546c63c88c519587e4b171cf))
* persist and search workspace models ([64e91d1](https://github.com/CubelliJ/harness/commit/64e91d1440da6f259736d97b89b4641a24fdbd90))

## [0.26.0](https://github.com/CubelliJ/harness/compare/v0.25.0...v0.26.0) (2026-08-24)


### Features

* support image context in conversations ([fa104ee](https://github.com/CubelliJ/harness/commit/fa104ee51ef659b78e6683ddae0f65224d426d16))
* support image context in conversations ([9d71752](https://github.com/CubelliJ/harness/commit/9d7175287478f6c8c35c5e1318c8e308a6e17b6e))

## [0.25.0](https://github.com/CubelliJ/harness/compare/v0.24.0...v0.25.0) (2026-08-24)


### Features

* bound file reads to protect context ([f5b9d52](https://github.com/CubelliJ/harness/commit/f5b9d52ef1df93bd69a83c4e7abbd5bb87c2cc6a))
* bound git diff output ([fd69f9a](https://github.com/CubelliJ/harness/commit/fd69f9af797f6398c6c2147536bde009dc910360))
* bound git diff output ([a957494](https://github.com/CubelliJ/harness/commit/a95749498aef6881e4b8b44a0a70c6fa99314ac4))

## [0.24.0](https://github.com/CubelliJ/harness/compare/v0.23.0...v0.24.0) (2026-08-24)


### Features

* interrupt active agent with Escape ([56f9a0a](https://github.com/CubelliJ/harness/commit/56f9a0a0de9c35b2b68878931c6fc37eaf80e6eb))
* make agent interruption robust ([827f541](https://github.com/CubelliJ/harness/commit/827f541e6794d754d82228c7dc0af53e4ee5e29c))


### Bug Fixes

* handle confirmation input bytes ([18e4347](https://github.com/CubelliJ/harness/commit/18e434788b47413cf5d203f56ce8ce83980a66bf))
* make escape interruption tool-safe ([717915d](https://github.com/CubelliJ/harness/commit/717915d4779f511f19627b16dee4231fb0983ceb))
* reduce interruption status noise ([d528598](https://github.com/CubelliJ/harness/commit/d528598d1a121f95e2a56b489d0dd66f159fa8db))

## [0.23.0](https://github.com/CubelliJ/harness/compare/v0.22.1...v0.23.0) (2026-08-24)


### Features

* add conversation cost monitoring ([62dc0e3](https://github.com/CubelliJ/harness/commit/62dc0e35a49ea5bb9cde0b87e7c5d2ca2e0cd2ab))
* add conversation cost monitoring ([df42f2c](https://github.com/CubelliJ/harness/commit/df42f2c184b043ff750ca29b7f386dfe765e9c00))
* report cached input tokens ([e31ffa7](https://github.com/CubelliJ/harness/commit/e31ffa74b45bb6cb96e96a0fff7b5af9b6e6040d))

## [0.22.1](https://github.com/CubelliJ/harness/compare/v0.22.0...v0.22.1) (2026-08-20)


### Reverts

* roll back image input ([a37f289](https://github.com/CubelliJ/harness/commit/a37f2894e7b3bfaa1a652472b933c7d530a04dac))

## [0.22.0](https://github.com/CubelliJ/harness/compare/v0.21.0...v0.22.0) (2026-08-20)


### Features

* add image input support ([4275442](https://github.com/CubelliJ/harness/commit/42754421f3847ae769f9741e090c4f57990d8a23))
* detect dropped images in prompt input ([e957415](https://github.com/CubelliJ/harness/commit/e957415aab49a3b73e08210b3e81b6a223fe405d))
* support image context in conversations ([3c4ea4b](https://github.com/CubelliJ/harness/commit/3c4ea4bf72473274d43f55eec049a00a3fa7a65c))
* support image context in conversations ([0ffeba1](https://github.com/CubelliJ/harness/commit/0ffeba1237eaf480a99be9244a1e40e1a1b6a873))

## [0.21.0](https://github.com/CubelliJ/harness/compare/v0.20.0...v0.21.0) (2026-08-19)


### Features

* elevate terminal visual experience ([#53](https://github.com/CubelliJ/harness/issues/53)) ([6e30cd6](https://github.com/CubelliJ/harness/commit/6e30cd6e3fc98f08195173b0cd2492685071299a))

## [0.20.0](https://github.com/CubelliJ/harness/compare/v0.19.0...v0.20.0) (2026-08-19)


### Features

* add native read-only git tools ([f40fa75](https://github.com/CubelliJ/harness/commit/f40fa755065db1499db53228d35a23d9dae1dd46))
* add native read-only git tools ([f28567c](https://github.com/CubelliJ/harness/commit/f28567ca161bf607a9bdc7f34bb904ba67a59288))

## [0.19.0](https://github.com/CubelliJ/harness/compare/v0.18.0...v0.19.0) (2026-08-19)


### Features

* add session persistence and resume support ([583a55a](https://github.com/CubelliJ/harness/commit/583a55af47dfa4c22b6e666ecf0458d821ab44f1))

## [0.18.0](https://github.com/CubelliJ/harness/compare/v0.17.0...v0.18.0) (2026-08-19)


### Features

* add conversation compaction controls ([8197948](https://github.com/CubelliJ/harness/commit/8197948ec51a7e9a178f72be53e79ebb2e712f5f))
* add conversation compaction controls ([c646f79](https://github.com/CubelliJ/harness/commit/c646f79740da608f10755a2102d82b9c7a89a473))

## [0.17.0](https://github.com/CubelliJ/harness/compare/v0.16.4...v0.17.0) (2026-08-18)


### Features

* add OpenRouter model selector ([7402694](https://github.com/CubelliJ/harness/commit/74026944f4a58a9f71e15f5cb81a3cbff81139bc))
* add OpenRouter model selector ([96f0a4c](https://github.com/CubelliJ/harness/commit/96f0a4c4a55076a0b0e3af40fe86dcbfb3e6c98e))

## [0.16.4](https://github.com/CubelliJ/harness/compare/v0.16.3...v0.16.4) (2026-08-18)


### Documentation

* simplify readme and split documentation ([ac7837b](https://github.com/CubelliJ/harness/commit/ac7837b7e5c8b0527687dc09073ff5dc57fe65d8))
* simplify readme and split documentation ([cf214d5](https://github.com/CubelliJ/harness/commit/cf214d5d163687d4820d3d59db1f8aac7402e268))

## [0.16.3](https://github.com/CubelliJ/harness/compare/v0.16.2...v0.16.3) (2026-08-18)


### Bug Fixes

* harden public GitHub Actions and reporting ([a2e836b](https://github.com/CubelliJ/harness/commit/a2e836b6c4c5152e17a12e826aa5ca2708bec39c))
* harden public GitHub Actions and reporting ([37f91ec](https://github.com/CubelliJ/harness/commit/37f91ec69c3f23551365b467545d9784f49bfca3))

## [0.16.2](https://github.com/CubelliJ/harness/compare/v0.16.1...v0.16.2) (2026-08-18)


### Bug Fixes

* bump and tag versions automatically on develop ([94154d6](https://github.com/CubelliJ/harness/commit/94154d6372690dd080992a5f12d6fe13accfcf5d))
* cut the version tag in the same release workflow ([1e0ffc6](https://github.com/CubelliJ/harness/commit/1e0ffc65b660892cbb3071953e3cc1c707216857))

## [0.16.1](https://github.com/CubelliJ/harness/compare/v0.16.0...v0.16.1) (2026-08-18)


### Bug Fixes

* ensure release tags are created after auto-merge ([fbf4e59](https://github.com/CubelliJ/harness/commit/fbf4e59064be886feaecc021a3c337d10f8a6e4a))
* ensure release tags are created after auto-merge ([bfb9a4c](https://github.com/CubelliJ/harness/commit/bfb9a4ccc2eaef531e6cf0fc77912b5a232402b4))

## [0.16.0](https://github.com/CubelliJ/harness/compare/v0.15.0...v0.16.0) (2026-08-18)


### Features

* add pull request skill ([dd928a6](https://github.com/CubelliJ/harness/commit/dd928a6391f3f24c4809f435c45fefd3dc2e11fa))
* add pull request workflow skill ([4bc0903](https://github.com/CubelliJ/harness/commit/4bc0903a3db7dd5d7cf5c638c31eaed2f8ca1feb))


### Bug Fixes

* compare work status against origin develop ([501306a](https://github.com/CubelliJ/harness/commit/501306a3587231305ca37f234e00f09c4b15d7a5))

## [0.15.0](https://github.com/CubelliJ/harness/compare/v0.14.0...v0.15.0) (2026-08-18)


### Features

* add MIT license ([ce8d9f0](https://github.com/CubelliJ/harness/commit/ce8d9f0e7cda4534340166ee54de306ecd70cb66))
* add MIT license ([7c22942](https://github.com/CubelliJ/harness/commit/7c229429d8a37d1c14d4ef1c9e947bb0a02ff050))

## [0.14.0](https://github.com/CubelliJ/harness/compare/v0.13.1...v0.14.0) (2026-08-18)


### Features

* add lazy-loaded workspace skills ([ba0c1c5](https://github.com/CubelliJ/harness/commit/ba0c1c5af76325996989a6eda265b3a226d9f63a))
* add lazy-loaded workspace skills ([11ca3af](https://github.com/CubelliJ/harness/commit/11ca3af16abf0e90b09b28232b115d0a04e25cef))

## [0.13.1](https://github.com/CubelliJ/harness/compare/v0.13.0...v0.13.1) (2026-08-18)


### Bug Fixes

* preserve history in main promotions ([bab8702](https://github.com/CubelliJ/harness/commit/bab8702b8e291f48a8ffdf96dfd7448ebb4559ae))
* preserve history in main promotions ([553bdfe](https://github.com/CubelliJ/harness/commit/553bdfe10afa5bf44de7ec2a776cce5249c1d746))

## [0.13.0](https://github.com/CubelliJ/harness/compare/v0.12.0...v0.13.0) (2026-08-18)


### Features

* show model context usage ([5892fd8](https://github.com/CubelliJ/harness/commit/5892fd8168ad7704e6b0139f5dc5d2b695f610fa))
* show model context usage ([#18](https://github.com/CubelliJ/harness/issues/18)) ([6de9b76](https://github.com/CubelliJ/harness/commit/6de9b768e8544eca21cb9b3cfffedc3321afe50f))

## [0.12.0](https://github.com/CubelliJ/harness/compare/v0.11.0...v0.12.0) (2026-08-18)


### Features

* default confirmations to yes ([a3688f0](https://github.com/CubelliJ/harness/commit/a3688f0cb73217daa596b70fa4b5d326b6af60f2))
* default confirmations to yes ([672f40a](https://github.com/CubelliJ/harness/commit/672f40ae2063c2abf579521e2f0e5ababa6bb024))

## [0.11.0](https://github.com/CubelliJ/harness/compare/v0.10.0...v0.11.0) (2026-08-18)


### Features

* load workspace agent instructions ([713cdf6](https://github.com/CubelliJ/harness/commit/713cdf6fcc2915341e2272bea722d7e736881455))
* load workspace agent instructions ([bf77ca3](https://github.com/CubelliJ/harness/commit/bf77ca3f4df9625ca9a9931212bafee603e40d93))


### Bug Fixes

* auto-merge release pull requests ([#14](https://github.com/CubelliJ/harness/issues/14)) ([554cd88](https://github.com/CubelliJ/harness/commit/554cd8823a6ea3e4b3f7a9e03f51ac30473d8eb1))
* merge clean release pull requests ([#15](https://github.com/CubelliJ/harness/issues/15)) ([1cdca94](https://github.com/CubelliJ/harness/commit/1cdca940510f267cbe01746593139e46730928e4))

## [0.10.0](https://github.com/CubelliJ/harness/compare/v0.9.0...v0.10.0) (2026-08-18)


### Features

* add bracketed multiline write and paste support to CLI input ([099a147](https://github.com/CubelliJ/harness/commit/099a147b3c96aeb224b0c335cb48cacbd94d5679))
* add diffs to files and ask for confirmation ([46ac226](https://github.com/CubelliJ/harness/commit/46ac226acc94bc154f9da0375a30bcf5c2478860))
* add installable package and guided setup ([455695f](https://github.com/CubelliJ/harness/commit/455695f797ef2e90171342f787fcd320b13d8504))
* add markdown support ([bfba12d](https://github.com/CubelliJ/harness/commit/bfba12d28282af2988e23d4090ff4a40d0473a04))
* add run_command function ([4481e54](https://github.com/CubelliJ/harness/commit/4481e54328d9a537b0d38967be1ac24349040be3))
* eval scenarios ([d8cca2a](https://github.com/CubelliJ/harness/commit/d8cca2ae4ff8c7b37eb2bd52dd86fed9e61c6ef6))
* implement native function call ([374f91e](https://github.com/CubelliJ/harness/commit/374f91ecb77c3575cb84c6a1d64a26cfaf3fd857))
* search_files function excluding gitignored files, changed how backups work ([8385350](https://github.com/CubelliJ/harness/commit/8385350ec6497015706393888f857998c03eaea2))
* stt with /voice mode ([780f79b](https://github.com/CubelliJ/harness/commit/780f79be072e4e929f7d9fe01294bbb289570624))


### Bug Fixes

* auto-merge develop release PRs ([170a9e2](https://github.com/CubelliJ/harness/commit/170a9e2744b80776cf145b1e686aa12aae3c3bd0))
* automate and validate develop releases ([0827b2b](https://github.com/CubelliJ/harness/commit/0827b2b01343dd5029f55122a7deedba9a1e0728))
* target releases at develop ([837df36](https://github.com/CubelliJ/harness/commit/837df36f9ef3443520098d4168674180b87f3f7c))
* track root package for automated releases ([9014a3b](https://github.com/CubelliJ/harness/commit/9014a3be49df2f7fa9b7ba0c98878ca2f1d6c206))
* update source version during releases ([e9a4f97](https://github.com/CubelliJ/harness/commit/e9a4f97beba87515a95149d5a744001996ef786e))
* use pyproject as version source ([835117c](https://github.com/CubelliJ/harness/commit/835117c091324367c7e3453abdda231a665f4f9b))
* use Python release strategy ([0c3f536](https://github.com/CubelliJ/harness/commit/0c3f5363cc5b5f5589db512fd6041de715549307))
* verify automated version bump ([5fcd46b](https://github.com/CubelliJ/harness/commit/5fcd46b132ffed3b63fb7db92a82c783b4613c3b))
