# Ira for Windows

**Ira for Windows** lives in the tray. Press **Ctrl+Alt+Space** anywhere (or
the shortcut you chose in [Settings](#settings)), or click its icon, and a
panel opens where you type to Ira. Ira can then use
what your PC can do, for you, when you ask: find a file and read it, read
the window you are in, list your browser tabs, open an app or a link, or
read what you copied.

> vo PDF kahan hai jo kal download kiya?
>
> padh kar batao
>
> screen pe kya hai?

It is text only for now: talking by voice is on the Mac, iPhone and Android
apps. Ira reads nothing until you ask, and only with the skills you switch
on. See [what Ira can and cannot see](#what-ira-can-and-cannot-see).

## Install

There is no installer yet. Build it on Windows 10 (version 2004) or later
with the [.NET 10 SDK](https://dotnet.microsoft.com/download):

```powershell
git clone https://github.com/helloupendra/ira.git
cd ira\clients\windows
dotnet build Ira.Windows -c Release -p:Platform=x64
```

Then run `Ira.exe` from the build's output folder
(`Ira.Windows\bin\x64\Release\...\win-x64`). It carries what it needs with
it. One copy runs per Windows user; starting it again opens the panel.

## Pair it with your Ira

The first time, the panel opens on pairing. On your Ira, in **Your devices**,
pair a **Windows PC** (it asks your PIN): it shows a link and a code. Copy
the link (`https://ira.example.com/pair#code=...`) and Ira for Windows finds
it on the clipboard (or press **Paste**); or type the code and your Ira's
address. The PC's key is kept in Windows Credential Manager, for your
Windows user only. **Pair again…** is in the tray icon's menu.

## Ask, and say yes

Type in the panel and press Enter. When Ira proposes something that acts for
you, a card asks: **Yes** or **No** for a small step, your **PIN** for
anything that sends, spends or deletes (three wrong PINs lock actions for 15
minutes, as everywhere in Ira), or **Windows Hello** once you set it up in
Settings. The panel hides when you click elsewhere, unless you pin it.

## Settings

**Settings…** is in the tray icon's menu and in the panel's menu:

- **Shortcut**: Ctrl+Alt+Space, Ctrl+Shift+Space, Alt+Shift+Space or
  Ctrl+Alt+I. If another app already has the one you choose, Ira says so and
  keeps the one it had.
- **Folders Ira may use**: your user folder at first. Add folders inside it
  and Ira uses only those; add a folder elsewhere (`D:\Work`, say) and Ira
  may use it too. `AppData`, `.ssh`, hidden files and key files stay off
  wherever they are.
- **Start Ira when you sign in to Windows**: a value under your own Run key
  in the registry, nothing that needs an administrator.
- **Approving with Windows Hello**: type your Ira PIN once and Windows
  Hello makes a key that only your face, finger or Hello PIN unlocks; its
  public key goes to your Ira (`RS256`, see
  [Security](../security.md#2-approving-with-the-devices-own-key-built)). After that, a card that needs your PIN also
  has **Windows Hello**. **Turn off** forgets the key on the PC.
- **What Ira may use on this PC**: each skill, on or off here. A skill works
  only when it is on for this PC on your Ira (with your PIN) and on here;
  switch it off here and the PC refuses it, whatever your Ira asks.

**What I read** (in the same window, and in the tray icon's menu) lists what
Ira used on this PC since it started, newest first: the file, the search,
the window or the app, never what it read. It stays on the PC, in memory
only, until Ira quits; **Clear** empties it.

## Drop: send anything to your other devices

Drop is your own inbox, shared by your devices (see
[Privacy](../privacy.md#drop)). The panel's Drop lists the newest items:
**Copy** first for text and links, a file to save or open.

- **Ctrl+Alt+Shift+V** sends the clipboard (text, or files copied in
  Explorer); **Ctrl+Alt+Shift+C** copies the newest item. Both are also in
  the tray icon's menu.
- In Explorer, **Send to → Ira (your devices)** sends the files you chose.
- Something new from another device comes as a notification with **Copy**;
  a file goes to `Downloads\Ira`, with **Show in folder**.

## What Ira can and cannot see

Each ability belongs to a **skill** you switch on for this PC on **Your
devices**, and then allow on the PC too: the panel asks once. The PC checks
both itself, so not even a server that asks can use a skill you did not
allow here.

| Skill | Tools | Tier |
| --- | --- | --- |
| files | find files, read one (PDF, Word, RTF, text, Markdown), open one | 0, 0, 1 |
| screen | read the text of the window you are in | 0 |
| browser | list the tabs in Chrome, Edge, Brave, Firefox, Vivaldi and Opera; bring one to the front | 0, 1 |
| apps | open an app from the Start menu; open a web link | 1, 2 |
| clipboard | read what you copied | 0 |
| control | type, press keys, click a control by its label, scroll: in the window you are in or an app you name, each step after your PIN or within an approval it opened | 3 |
| routine | tell your Ira when the PC locks, unlocks, sleeps and wakes, its first activity of the day, and which network it is on (see [Routine](#routine)) | — |

Ira **cannot**:

- read anything you did not ask about; nothing runs in the background;
- send a picture of your screen: Windows' own text recognition reads the
  window on the PC, and only the words go to your Ira;
- read the windows of password managers (1Password, Bitwarden, KeePass,
  LastPass and others), the Windows sign-in or administrator prompt, or the
  lock screen;
- read `AppData` (browser profiles, saved passwords, mail), `.ssh`, `.aws`
  and other credential folders, hidden or system files, or files that hold
  keys and passwords (`.env`, `.pem`, `.key`, `id_rsa`, password vaults),
  even if you ask; links and junctions are followed first, and network
  paths, device paths and alternate data streams are refused;
- read outside your user folder, or outside the folders you chose in
  Settings;
- open a terminal, PowerShell, the Command Prompt or Task Manager, a
  program, script or shortcut file, or a link that is not a plain
  `https://` or `http://` address;
- read what a password manager copied and marked as private;
- type, press keys or click in a terminal, PowerShell, the Command Prompt,
  Task Manager, a password manager or the sign-in or administrator prompt
  (the PC checks the program itself, whatever your Ira asks); type into a
  password field; or press the Windows key, which opens Run.

What Ira reads goes to your own Ira server, marked as data that can never
give Ira orders, and is kept only in that conversation.

## Routine

If you switch on the **routine** skill for this PC (on your Ira, and in
Settings here), Ira for Windows tells your Ira every 30 seconds, when
something changed: when the PC locks, unlocks, sleeps and wakes, its first
activity of the day, and which network it is on, as a code made from the
network's gateway with a salt kept on this PC. Never the network's name,
never what is on the screen or which apps run. The codes are the Mac's
kind, so a network you name **Office** is Office for both. See [What Ira
learns](../learning.md).

## Remove Ira from this PC

**Forget this pairing…** in the panel's menu tells your Ira to stop this PC's key and
forgets it here; or remove the PC on your Ira, under **Your devices**.
Delete the folder you built it in to remove the app.
