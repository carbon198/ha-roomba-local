# Roomba Local for Home Assistant

[![Tests](https://github.com/carbon198/ha-roomba-local/actions/workflows/test.yaml/badge.svg)](https://github.com/carbon198/ha-roomba-local/actions/workflows/test.yaml)
[![Release](https://img.shields.io/github/v/release/carbon198/ha-roomba-local)](https://github.com/carbon198/ha-roomba-local/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Control and monitor your V4 Roomba through the [Roomba Cloud emulator](https://github.com/carbon198/roomba-cloud), without the iRobot cloud.

This is a custom Home Assistant integration. The emulator runs separately and handles the robot connection.

## Features

- Vacuum controls: start, pause, stop, return to dock and locate.
- Room cleaning through Home Assistant's vacuum area mappings.
- Battery, mission status, robot errors and dock diagnostics.
- Supported robot settings and cleaning-mode selection.
- Saved-map images with live position and mission trails.
- Reported model/SKU, firmware and serial number when available.
- Local push updates, automatic reconnection and reauthentication.

Available features depend on what your robot reports. Tested hardware: **Roomba 505 / V4**.

## Requirements

- **Home Assistant 2026.10 or newer**.
- A running [roomba-cloud](https://github.com/carbon198/roomba-cloud) emulator with your robot connected.

Follow the [emulator setup guide](https://github.com/carbon198/roomba-cloud#readme) for deployment, robot provisioning, certificates and obtaining your token.

## Installation

[![Open your Home Assistant instance and add this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=carbon198&repository=ha-roomba-local&category=integration)

Add this repository in HACS using the button above, download **Roomba Local**, then restart Home Assistant.

Alternatively, add `carbon198/ha-roomba-local` as a HACS custom repository with category **Integration**.

For manual installation, copy [`custom_components/roomba_local`](custom_components/roomba_local) into your HA configuration's `custom_components` directory and restart.

## Configuration

1. Open **Settings → Devices & services → Add integration**.
2. Choose **Roomba Local**.
3. Enter the emulator HTTPS URL and customer token.
4. Select your robot.

Add another integration entry for each additional robot. Each has its own device, settings and room mappings.

Use **Reconfigure** to change the server URL or token without changing existing entity identities.

## Maps and controls

Configure room-to-area mappings on the vacuum entity for room cleaning. Choose the cleaning mode using the integration's select entity.

Map images show saved floor plans, reported positions and mission trails—not measured cleaning coverage. Delete maps through the emulator's web editor; confirmed robot-side deletion removes their HA image entities.

Controls and settings remain robot-reported, not optimistic. Commands are not replayed when a disconnected robot returns.
