# VSCode Chat Browser
Python based browser for VSCode Chats. Backup, Copy, and Repair

## About this project

I had not been using VSCode workspaces with multiple folders and recently discovered this wonderful feature. 

I was suddenly able to provide my copilot chat additional context by providing folders of documentation in the same workspace without having to copy or move that documentation around. 

But this presented the problem of wanting to merge several single folder vscode copilot sessions into a workspace session.

So I created a merge script, but then was curious if it had copied everything and needed to add verification. I had found people renaming workspaces or moving folders lose their chat sessions, so it sounded like a bit more user control was needed.

A portable cross platform "VSCode Chat Browser" was born to solve this.

Suddenly I can see my history with datestamps and modification times. I can repair indexes for VSCode, and I have control to search, backup, copy, delete, and transfer as I need.

Hope you enjoy and you find it useful!

If you do, please consider buying me a coffee! 
https://buymeacoffee.com/trespassvr

Contact me for consulting, sponsorship, or FTE opportunities.

## How to use

1. Find your workspace chat folder. It will be automatically detected, but it is user configurable.
    Windows default: `~/AppData/Roaming/Code/User/workspaceStorage/`
    macOS default: `~/Library/Application Support/Code/User/workspaceStorage`
    Linux default: `~/.config/Code/User/workspaceStorage`
2. Make a snapshot backup (aka zip/tar/etc) of this folder and put it somewhere safe. There is a button in the UI to do this if that is easier.
3. Since this is a self-contained Python 3/tkinter UI, you only need to have Python 3 installed on your computer. No other dependencies exist.
4. Download the latest release of this project.
5. **Close all windows of VSCode before using.**
6. Run the included launcher:
    `workspace_chat_browser_Win.bat` (Windows) or
    `workspace_chat_browser_macOS.terminal` (macOS) or
    `python3 src/workspace_chat_browser.py` in your terminal of choice.


## Developing

- Collaboration is welcome and encouraged!
- pytest is the only current dependency for making sure the code has good test coverage and regressions can be found.
- This project is pip installable.
- A Command Line Interface entry point is provided.