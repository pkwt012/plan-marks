# Plan Marks

Local tool for marking electrical symbols on PDF floor plans. The PDF never leaves this computer.

Open a plan, click a symbol, then click the sheet. Drag a mark to move it, drag the amber handle to rotate it, and export a new PDF with the symbols drawn on top of the original sheet.

## Windows

Download the latest build from the [releases page](https://github.com/pkwt012/plan-marks/releases). Unzip the folder and double-click `PlanMarks.exe`. Your browser opens the plan marker. Leave the small Plan Marks window open while you work, and close it to quit. Keep `PlanMarks.exe` and the `_internal` folder together.

Windows may say it protected your PC, because the program is not signed. Choose More info, then Run anyway.

## Run from source

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

On Windows, use `py -3` instead of `python3` for those commands. Then use the page that opens (by default [http://127.0.0.1:8765](http://127.0.0.1:8765)). Press Ctrl+C in the terminal to stop.

To rebuild the Windows program on a Windows PC:

```bat
py -3 -m pip install -r requirements.txt pyinstaller
py -3 -m PyInstaller packaging\planmarks.spec
```

The program is in `dist\PlanMarks\`.

PyMuPDF is the only dependency. There is no account, no upload, and no network call except the browser talking to this local server.

## Use

- **Open PDF** loads one file. **Add sheets** appends every page from another PDF. **Legend** adds a sheet that lists every symbol with its name and description.
- **Dashed line** draws a switch leg between lights. Click the first point, then the next. It stays armed so you can draw another. Esc cancels the segment, then puts the tool away. Drag a finished line to move it, or drag an amber end to change it.
- **Drop legend** places a key of every symbol on the current sheet. Drag it to a clear spot. The width slider scales it. The header **Legend** button still adds a full sheet with the longer descriptions.
- **Try the sample plan** is a two-sheet house drawn at 1/4" = 1'-0", with a 10 ft dimension for calibration.
- Click a palette symbol to arm it, then click the plan. Click the symbol again, or press Esc, to stop placing.
- Drag to move. Drag the amber handle to rotate (Shift snaps to 15°). Letters stay upright. Duplex bars and the wall light turn with the symbol.
- **Duplicate**, **Delete**, or the size slider edit the selected mark. Small / Medium / Large set a paper size. **1 ft** (after calibration) makes the symbol box one foot on the plan.
- **Calibrate**: click two ends of a known length, enter that length, and Apply. The sample's living-room dimension is 10 feet.
- **Export PDF** writes a new file. The original plan stays vector; symbols are vector too.
- **Save** writes a JSON marks file. **Load** puts those marks back. The same PDF also restores marks automatically in this browser.

Wheel zooms, and the zoom percentage is paper size (100% is actual size). Right-drag or Space-drag pans. Fit and the percentage button are in the header. The **?** button lists shortcuts.

## Add a symbol

Drop an SVG into `symbols/` and add an entry to `symbols/catalog.json`. A file with no catalog entry still shows up under Custom.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <g class="rot" fill="none" stroke="#141414" stroke-width="4" stroke-linecap="round">
    <circle cx="50" cy="50" r="33" fill="#ffffff" stroke="none"/>
    <circle cx="50" cy="50" r="24" fill="#ffffff"/>
  </g>
  <text class="label" x="50" y="58" text-anchor="middle"
        font-family="Helvetica" font-size="22" font-weight="700" fill="#141414">X</text>
</svg>
```

- `viewBox` must be `0 0 100 100`. The box is the symbol's size on the sheet.
- Draw ink as `#141414`. White shapes are the knockout behind the symbol. The ink color is replaced when a mark is red, blue, green, or orange.
- Put geometry that should turn (outlet bars, a light, the panel) in `class="rot"`. It rotates around the center, 50, 50.
- Put letters and pictures that should stay upright in `class="label"`.
- Use double quotes on the `class` attribute. Restart the app after adding a file.

Catalog fields: `id`, `name`, `category`, `file`, and optional `wall`, `keywords`, `hint`, `defaultColor`.

## Check

```bash
.venv/bin/python tests/selftest.py
```
