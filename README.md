# Audio Visualizer

Displays a real-time audio spectrum on Framework 16 LED matrices. Captures system audio and shows frequency bars on both left and right matrix modules.

![Demo](demo.gif)

## Running it

```bash
nix run .
```

Then just play some music.

## Options

- `--brightness N` - set LED brightness (0-255, default 100)
- `--smoothing N` - how much to smooth the bars (0.0 = reactive, 0.9 = smooth)
- `--mirror` - puts low frequencies in the middle, highs at top/bottom
- `--mono` - use mono audio instead of stereo
