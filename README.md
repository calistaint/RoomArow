

# Roomarow Multiplayer
<img width="1853" height="724" alt="title" src="https://github.com/user-attachments/assets/d3c53117-c39d-48a6-8cd4-799dcf481cb4" />

Roomarow is an open-source, cooperative multiplayer dungeon crawler written in Python using Pygame. Players traverse procedurally generated floors, fight waves of distinct enemies, collect various weapons, and challenge evolving bosses.

## Features

*   **Multiplayer Co-op:** Host a game locally or connect via IP address to play with friends. Support for spectating after death.
*   **Procedural Generation:** Every floor is uniquely generated with different room layouts, enemy placements, and chest locations.
*   **Combat System:**
    *   **Weapons:** 9 different weapon types including Shotguns, Snipers, Miniguns, Laser Rifles, and Grenade Launchers.
    *   **Enemies:** Over 12 enemy types with unique AI behaviors (Teleporters, Shielders, Healers, Dodgers, etc.).
    *   **Bosses:** 4 distinct boss variants (Standard, Summoner, Rusher, Orbweaver) with multi-stage attack patterns.
*   **Progression:** Difficulty scaling based on floor depth and boss kills.
*   **Audio:** Custom procedural sound generation engine using NumPy (no external audio assets required, though supported).
*   **Interface:** Includes a minimap, health bars, dash cooldowns, and a settings menu.

## Prerequisites

To run the source code, you need Python installed (tested on Python 3.12) along with the following libraries:

*   pygame
*   numpy (required for sound generation)

## Installation

1.  Download the files in the Repo

2.  Install the required dependencies:
    ```bash
    pip install pygame numpy
    ```

## How to Play

### Running the Game
To start the game from the source code, run:

```bash
python main.py
```

### Controls

| Key | Action |
| :--- | :--- |
| **W, A, S, D** | Move Player |
| **Mouse Cursor** | Aim |
| **Left Click** | Shoot |
| **Left Shift / Right Shift** | Dash |
| **E** | Interact (Open Chests) |
| **M** | Toggle Minimap |
| **ESC** | Pause Menu |
| **J** | Accept Level Transition (when standing on trapdoor) |
| **TAB** | Change Name Color (in Main Menu) |
| **R** | Restart Game (Host only, on Game Over screen) |

### Multiplayer Guide

The game uses a Client-Host architecture.

1.  **Hosting:**
    *   Select **Multiplayer** > **Host** in the main menu.
    *   You will enter the lobby. Wait for other players to join.
    *   Once ready, press **SPACE** or click **START OP** to generate the dungeon.

2.  **Joining:**
    *   Select **Multiplayer** > **Join** in the main menu.
    *   Enter the Host's IP address.
        *   If playing on the same machine, you can use `127.0.0.1` or `localhost`.
        *   If playing on the same Wi-Fi/LAN, use the Host's local IPv4 address (e.g., `192.168.1.x`).
        *   If playing over the internet, the Host must port forward port **5555** (TCP).
    *   Click **Connect**.

### Gameplay Loop

1.  **Explore:** Navigate through rooms. New rooms will lock until all enemies inside are defeated.
2.  **Loot:** Find Chests (marked Gold on the minimap) to acquire random weapons.
3.  **Boss:** Locate the Boss room (marked Red on the minimap). You must explore at least 70% of the map to unlock the boss door.
4.  **Advance:** Defeating the boss reveals a trapdoor. All players must stand on the trapdoor and press **J** to advance to the next floor.

## Building from Source

To create a standalone executable (`.exe`) for Windows, you can use PyInstaller. Ensure you have `pyinstaller` installed (`pip install pyinstaller`).

Run the following command in your terminal:

```bash
pyinstaller --noconfirm --onefile --windowed --name "roomarow" --icon "icon.png" --add-data "sfx;sfx" --add-data "title.png;." --add-data "calistasplash.png;." --add-data "gamemusic.mp3;." --add-data "menumusic.mp3;." --add-data "icon.png;." main.py
```

*Note: You may need to adjust the path to python.exe or pyinstaller depending on your environment variables.*

## Configuration

The game saves your preferences (Username, Volume Settings) automatically in a `data/settings.json` file generated upon the first launch.
