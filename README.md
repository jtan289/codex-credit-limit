# Codex Credit Limit for Pock

[English](README.md) | [简体中文](README.zh-CN.md)

Display Codex five-hour and weekly usage limits, reset times, and the number of currently running Codex tasks on the MacBook Touch Bar.

![Widget preview](en/Codex%20Credit%20Limit.pock/Contents/Resources/widget-preview.png)

## Features

- Shows the five-hour and weekly usage windows
- Displays either remaining or used quota
- Shows the reset time for each usage window
- Displays the number of currently running Codex tasks
- Includes both English and Simplified Chinese Pock widgets
- Reads data only from the locally authenticated Codex App or CLI; no API key is included

## Requirements

- macOS 10.15 or later
- An Apple Silicon Mac (the bundled native components target `arm64`)
- Codex App or Codex CLI installed and signed in
- Pock

## Installation

1. Download or clone this repository.
2. Choose your preferred language bundle:
   - `en/Codex Credit Limit.pock`
   - `简中/Codex 额度.pock`
3. Double-click the `.pock` file and complete the installation in Pock.

## How it works

The widget reads the account usage windows through the local Codex App Server and caches the latest successful result in:

```text
~/Library/Caches/CodexTouchBar/
```

It also reads task lifecycle records from the local `~/.codex/sessions` directory to count active top-level tasks. All processing stays on the local machine.

## Repository structure

```text
.
├── en/
│   └── Codex Credit Limit.pock/
└── 简中/
    └── Codex 额度.pock/
```

Each widget bundle includes the Python backend, precompiled `arm64` renderer and Pock bundle, icon, and preview image.

## Author

[jtan289](https://github.com/jtan289)

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

Codex and OpenAI are trademarks of OpenAI. This community project is not affiliated with or endorsed by OpenAI.
