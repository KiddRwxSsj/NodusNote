# ModusNote

ModusNote is a desktop notes application for Windows. I built it because I wanted something lightweight that could stay pinned on top of other windows, but with a more personal vibe (dark themes, a retro/Metal Gear aesthetic, and mechanical typing sounds).

It doesn't require a complex installation. It's a single portable executable that saves everything in its own folder without cluttering your system.

## AI Usage

Parts of this project were developed with the assistance of AI tools.  
AI was mainly used to accelerate prototyping, refactor sections of code, explore UI ideas, and reduce repetitive boilerplate work.

All architecture decisions, debugging, feature integration, and final implementation choices were reviewed and adapted manually.

## Where are my notes saved?
If you're looking for your saved data, it's right next to the `.exe`! 

When you run the app, it automatically creates a folder called **`.modus_data`** in the exact same location where your `ModusNote.exe` is sitting. Inside that folder, there is a file called `state.json`. That file contains all your text, tasks, window size, and settings. 
*(Tip: Since the folder name starts with a dot, make sure you're looking in the same directory where you extracted the program).*

## What exactly does it do?
- **Notes & To-Do:** Separate tabs for free-text notes and a task list (with checkboxes and time tracking).
- **Always on top:** The window floats above your other applications. 
- **Lock Mode:** You can lock the window so you don't move it by accident. It also makes it click-through, meaning you can interact with whatever is behind it while still reading your notes.
- **Themes & Opacity:** Switch between several themes (Onyx, Ivory, Classic, Shadow Moses, Python Eater). You can adjust the background transparency and the accent colors.
- **Immersive Audio:** It plays a sound every time you type. Different themes have different sound profiles.

***

## Technical Notes (For future me or anyone tweaking the code)

If you want to dive into the code later, here's a quick rundown of how the guts of the app actually work:

### 1. User Interface (PyQt6)
The whole UI is built with `PyQt6`. 
- **Borderless Window:** I used the `FramelessWindowHint` flag to remove the default Windows borders. Window dragging is coded from scratch by capturing `mousePressEvent` and `mouseMoveEvent` on the top bar (`self.header`).
- **Theming (QSS):** PyQt6 uses QSS (which is basically CSS). If you want to change colors, margins, or borders, go straight to the `apply_theme()` function. There's a giant text block there with the stylesheet that gets injected dynamically based on the selected theme.
- **Hand-drawn Icons:** Buttons like the menu, trash can, or lock don't use image files. They are drawn pixel by pixel using `QPainter`. To change their shapes, check out the `CustomIconBtn` and `LockBtn` classes.

### 2. Audio Engine (Mathematically Generated!)
To keep the `.exe` as lightweight as possible, the app **does not use external mp3 or wav files**. 
- The typing sounds are generated on the fly using pure sine waves (`math.sin`) and random noise.
- The code builds a `.wav` file directly in the temporary memory (using the `wave` and `struct` libraries) and then plays it using the native Windows `winsound` library.
- If you want to tweak the sounds or make a new one, look for the `AudioEngine` class and play around with the frequencies in `_shadow_moses_bytes` or `_python_eater_bytes`.

### 3. Auto-Save (JSON)
No heavy databases here. Everything is saved to a plain text file (`state.json`) inside the `.modus_data` folder.
- **When does it save?** To avoid trashing your hard drive by saving on every single keystroke, there's a `QTimer` set to 700 milliseconds. When you stop typing for 0.7 seconds, the app detects you are "idle" (`on_idle`) and saves all your text, tasks, and settings (window size, theme, opacity) all at once.

### 4. Windows Autostart
The "Run at startup" option works by directly modifying the Windows Registry (`winreg`). It injects the path of the `.exe` into the current user's `Run` key.

### 5. Compiling
If you modify `modusnote.py` and need to generate a new `.exe`, this is the exact PyInstaller command you need to run in your terminal:
```bash
pyinstaller --onefile --windowed --icon=nodus.ico modusnote.py
```
*(Remember to delete the old `build` and `dist` folders before compiling again to keep things clean).*
